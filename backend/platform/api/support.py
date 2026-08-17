from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from json import JSONDecodeError
from typing import Any
from uuid import uuid4

from backend.platform.security import AuthenticationError, RateLimitExceeded
from backend.platform.reports.store import CommentRevisionConflict
from backend.platform.message_board.store import MessageBoardRevisionConflict
from backend.platform.tenancy import ExecutionContext


MAX_JSON_BODY_BYTES = 512 * 1024
MAX_UPLOAD_BODY_BYTES = 12 * 1024 * 1024


class RequestBodyTooLarge(ValueError):
    pass


@dataclass(frozen=True)
class APIRequestContext:
    user_id: str
    tenant_id: str

    def to_execution_context(self) -> ExecutionContext:
        return ExecutionContext(user_id=self.user_id, tenant_id=self.tenant_id)


def first_query_value(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    return values[0] if values else None


def send_route_exception(handler: Any, exc: Exception) -> None:
    request_id = str(handler.headers.get("X-Request-Id") or f"req_{uuid4().hex[:20]}")
    if isinstance(exc, RateLimitExceeded):
        handler._send_json(
            {
                "error": "rate_limit_exceeded",
                "message": "Too many requests. Retry after the indicated delay.",
                "request_id": request_id,
                "retry_after_seconds": exc.retry_after_seconds,
            },
            HTTPStatus.TOO_MANY_REQUESTS,
            headers={"Retry-After": str(exc.retry_after_seconds), "X-Request-Id": request_id},
        )
        return
    if isinstance(exc, AuthenticationError):
        handler._send_json(
            {"error": "authentication_required", "message": "Authentication is required.", "request_id": request_id},
            HTTPStatus.UNAUTHORIZED,
            headers={"X-Request-Id": request_id},
        )
        return
    if isinstance(exc, PermissionError):
        handler._send_json(
            {"error": "permission_denied", "message": "The requested operation is not permitted.", "request_id": request_id},
            HTTPStatus.FORBIDDEN,
            headers={"X-Request-Id": request_id},
        )
        return
    if isinstance(exc, RequestBodyTooLarge):
        handler._send_json(
            {"error": "request_body_too_large", "message": "The request body exceeds the allowed size.", "request_id": request_id},
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            headers={"X-Request-Id": request_id},
        )
        return
    if isinstance(exc, CommentRevisionConflict):
        handler._send_json(
            {
                "error": "comment_revision_conflict",
                "message": "Comments changed since this client loaded them. Refresh and retry.",
                "request_id": request_id,
                "current_revision": exc.current_revision,
            },
            HTTPStatus.CONFLICT,
            headers={"X-Request-Id": request_id},
        )
        return
    if isinstance(exc, MessageBoardRevisionConflict):
        handler._send_json(
            {"error": "message_board_revision_conflict", "message": "留言已在其他页面更新，请刷新后重试。", "request_id": request_id},
            HTTPStatus.CONFLICT,
            headers={"X-Request-Id": request_id},
        )
        return
    if isinstance(exc, JSONDecodeError):
        handler._send_json(
            {"error": "invalid_json", "message": "The request body is not valid JSON.", "request_id": request_id},
            HTTPStatus.BAD_REQUEST,
            headers={"X-Request-Id": request_id},
        )
        return
    if isinstance(exc, KeyError):
        handler._send_json(
            {"error": "not_found", "message": "The requested resource was not found.", "request_id": request_id},
            HTTPStatus.NOT_FOUND,
            headers={"X-Request-Id": request_id},
        )
        return
    if isinstance(exc, ValueError):
        validation_messages = {
            "duplicate_model_name": "模型名称已存在，请使用不同的模型名称。",
            "invalid_model_application_module": "应用模块不在系统登记的可选范围内。",
            "invalid_login_credentials": "邮箱或密码不正确，请确认后重试。",
            "analysis_selected_table_semantics_not_registered": "所选数据表尚未登记可执行的字段与指标映射，系统不会改用其他数据源。请在数据管理完成映射后重试，或选择已登记的数据表。",
            "analysis_production_data_table_required": "当前分析没有绑定可执行的数据表。请先在页面选择当前机构的数据表，再发起分析。",
            "analysis_automation_disabled": "智能分析任务已被管理员停用，请联系机构管理员启用后重试。",
            "automation_task_is_not_active": "智能分析任务当前不可运行，请刷新页面后重试；若仍失败，请联系机构管理员。",
        }
        metric_workbook_messages = {
            "请上传 .xlsx 格式的指标文件。": ("metric_workbook_file_type", "仅支持 .xlsx 格式的指标文件，请重新选择。"),
            "指标文件内容无效，请重新选择 .xlsx 文件。": ("metric_workbook_invalid_content", "指标文件内容无效，请重新选择 .xlsx 文件。"),
            "指标文件不能为空且不得超过 8MB。": ("metric_workbook_size_invalid", "指标文件不能为空且不得超过 8MB。"),
            "无法解析指标 Excel，请使用标准 .xlsx 模板。": ("metric_workbook_parse_failed", "无法解析指标 Excel，请确认文件未损坏并使用标准 .xlsx 模板。"),
            "Excel 中未找到指标数据。": ("metric_workbook_empty", "Excel 中未找到指标数据，请检查“指标库-指标体系”工作表。"),
            "Excel 缺少指标模板必填列，请使用“指标库-指标体系”工作表。": ("metric_workbook_columns_missing", "Excel 缺少模板必填列，请使用包含完整表头的“指标库-指标体系”工作表。"),
            "Excel 中没有可导入的指标名称。": ("metric_workbook_no_metric_names", "Excel 中没有可导入的指标名称，请填写“新指标名称”或“原指标名称”。"),
        }
        error_text = str(exc)
        message = validation_messages.get(error_text, "The request failed validation.")
        error_code = (
            error_text
            if error_text in {
                "analysis_selected_table_semantics_not_registered",
                "analysis_production_data_table_required",
                "analysis_automation_disabled",
                "automation_task_is_not_active",
            }
            else "invalid_request"
        )
        if error_text in metric_workbook_messages:
            error_code, message = metric_workbook_messages[error_text]
        if error_text == "name and email are required.":
            error_code = "access_user_identity_required"
            message = "姓名和邮箱不能为空。"
        if error_text.startswith("角色不存在，请检查："):
            error_code = "access_user_role_not_found"
            message = error_text
        if error_text.startswith("用户邮箱已存在"):
            error_code = "access_user_email_conflict"
            message = "该邮箱已绑定其他用户，请检查邮箱或编辑已有用户。"
        if error_text.startswith("Unsupported metric:"):
            error_code = "analysis_metric_not_bound_to_selected_data"
            message = "当前问题中的指标没有绑定到已选数据表。请先选择包含该指标的当前机构数据表，再发起分析。"
        if error_text.startswith("model_application_module_not_ready:"):
            module_label = error_text.split(":", 1)[1] or "目标应用模块"
            message = f"{module_label}尚未配置已鉴权成功的大模型，请在模型接入管理中完成配置和连接测试。"
        if error_text.startswith("metric_dictionary_duplicate_names:"):
            error_code = "metric_dictionary_duplicate_names"
            duplicate_names = error_text.split(":", 1)[1] or "所选"
            message = f"以下指标名称存在冲突：{duplicate_names}。请修改口径不同的重名指标，或移除指标库中已有的同名指标后再导入。"
        handler._send_json(
            {"error": error_code, "message": message, "request_id": request_id},
            HTTPStatus.BAD_REQUEST,
            headers={"X-Request-Id": request_id},
        )
        return
    handler._send_json(
        {"error": "internal_error", "message": "The service could not complete the request.", "request_id": request_id},
        HTTPStatus.INTERNAL_SERVER_ERROR,
        headers={"X-Request-Id": request_id},
    )


def format_prometheus_metrics(runtime_summary: dict[str, Any]) -> str:
    sample_size = int(runtime_summary.get("sample_size") or 0)
    ok_count = int(runtime_summary.get("ok_count") or 0)
    error_count = int(runtime_summary.get("error_count") or 0)
    cancelled_count = int(runtime_summary.get("cancelled_count") or 0)
    fallback_count = int(runtime_summary.get("fallback_count") or 0)
    avg_latency_ms = float(runtime_summary.get("avg_latency_ms") or 0)
    latency_sum_ms = int(runtime_summary.get("latency_sum_ms") or 0)
    return "\n".join(
        [
            "# HELP smart_data_agent_analysis_requests_total Analysis request count by status.",
            "# TYPE smart_data_agent_analysis_requests_total counter",
            f'smart_data_agent_analysis_requests_total{{status="ok"}} {ok_count}',
            f'smart_data_agent_analysis_requests_total{{status="error"}} {error_count}',
            f'smart_data_agent_analysis_requests_total{{status="cancelled"}} {cancelled_count}',
            "# HELP smart_data_agent_analysis_fallback_total Analysis requests served by semantic fallback.",
            "# TYPE smart_data_agent_analysis_fallback_total counter",
            f"smart_data_agent_analysis_fallback_total {fallback_count}",
            "# HELP smart_data_agent_analysis_latency_avg_ms Average analysis request latency in milliseconds over recent samples.",
            "# TYPE smart_data_agent_analysis_latency_avg_ms gauge",
            f"smart_data_agent_analysis_latency_avg_ms {avg_latency_ms}",
            "# HELP smart_data_agent_analysis_latency_ms_sum Cumulative analysis latency in milliseconds.",
            "# TYPE smart_data_agent_analysis_latency_ms_sum counter",
            f"smart_data_agent_analysis_latency_ms_sum {latency_sum_ms}",
            "# HELP smart_data_agent_runtime_sample_size Number of runtime samples used for the health summary.",
            "# TYPE smart_data_agent_runtime_sample_size gauge",
            f"smart_data_agent_runtime_sample_size {sample_size}",
            "",
        ]
    )
