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
    trace_id = str(handler.headers.get("X-Trace-Id") or request_id)
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
        status = HTTPStatus(getattr(exc, "status_code", HTTPStatus.UNAUTHORIZED))
        error_code = str(getattr(exc, "error_code", "authentication_required"))
        handler._send_json(
            {
                "error": error_code,
                "message": "Authentication is required." if status == HTTPStatus.UNAUTHORIZED else "Authenticated context conflicts with the request.",
                "request_id": request_id,
                "trace_id": trace_id,
            },
            status,
            headers={"X-Request-Id": request_id, "X-Trace-Id": trace_id},
        )
        return
    if isinstance(exc, PermissionError):
        error_text = str(exc)
        permission_messages = {
            "customer_segment_detail_table_required": "该数据源不是客户号唯一主键的明细表，不能用于分客群分析。",
            "customer_segment_page_data_customer_key_changed": "明细表的客户号主键已经变化，请由超级管理员在站内数据的“分客群页面”中重新保存配置。",
            "page_data_source_unavailable": "页面数据源已不可用。请检查当前机构的数据目录和页面数据绑定。",
            "page_data_source_schema_changed": "页面数据源结构已更新，当前图表字段不再兼容。请重新绑定数据源后保存。",
            "global_super_admin_required": "仅超级管理员可以执行该操作。",
            "tenant_catalog_super_admin_required": "仅超级管理员可以管理租户。",
            "global_super_admin_required_for_page_data": "仅超级管理员可以新增或修改页面数据。",
            "multi_institution_page_data_sources_unavailable": "当前账号已无法读取该多机构配置中的全部来源。请检查机构授权和表关联配置。",
            "multi_institution_page_data_source_schema_changed": "多机构数据源结构已更新，当前图表所用字段或关联键不再兼容。请重新确认关联后保存。",
            "raw_table_metadata_source_unavailable": "原始表已更新或不属于当前机构，请重新选择后再保存字段配置。",
        }
        if error_text in permission_messages:
            handler._send_json(
                {"error": error_text, "message": permission_messages[error_text], "request_id": request_id},
                HTTPStatus.FORBIDDEN,
                headers={"X-Request-Id": request_id},
            )
            return
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
        identity_messages = {
            "tenant_not_provisioned": ("tenant_not_provisioned", "目标机构尚未开通，请先确认机构目录。"),
            "user_not_provisioned": ("user_not_provisioned", "用户档案不存在或尚未生效，请检查用户状态后重试。"),
            "role_not_provisioned": ("role_not_provisioned", "角色尚未开通，请检查机构角色后重试。"),
        }
        error_text = str(exc.args[0]) if exc.args else "not_found"
        error_code, message = identity_messages.get(error_text, ("not_found", "The requested resource was not found."))
        handler._send_json(
            {"error": error_code, "message": message, "request_id": request_id},
            HTTPStatus.NOT_FOUND,
            headers={"X-Request-Id": request_id},
        )
        return
    if isinstance(exc, ValueError):
        validation_messages = {
            "duplicate_model_name": "模型名称已存在，请使用不同的模型名称。",
            "invalid_model_application_module": "应用模块不在系统登记的可选范围内。",
            "invalid_login_credentials": "账号或密码不正确，请确认后重试。",
            "login_survey_invalid": "调查问卷格式不正确，请刷新页面后重试。",
            "login_survey_answers_required": "请完整回答两个问题后再提交。",
            "login_survey_answer_too_long": "每个问题最多填写 1000 个字符。",
            "login_survey_identity_required": "无法确认问卷提交账号，请重新登录后再试。",
            "login_survey_institution_invalid": "请选择有效机构后再保存问卷。",
            "password_current_required": "请输入当前密码。",
            "password_current_incorrect": "当前密码不正确。",
            "password_new_required": "请输入新密码。",
            "password_new_too_short": "新密码至少 6 位。",
            "password_new_same_as_current": "新密码不能与当前密码相同。",
            "registration_contact_required": "请填写手机号或邮箱。",
            "registration_institution_required": "请选择要加入的机构。",
            "registration_institution_unknown": "所选机构不在系统目录中，请重新选择。",
            "tenant_name_required": "请填写租户名称。",
            "tenant_name_too_long": "租户名称不能超过 50 个字符。",
            "tenant_name_reserved": "该名称属于系统保留租户，不能使用。",
            "tenant_name_invalid": "租户名称包含不支持的字符。",
            "tenant_name_duplicate": "该租户已存在，请使用不同的名称。",
            "tenant_id_required": "缺少要操作的租户。",
            "tenant_not_found": "未找到对应租户，请刷新后重试。",
            "registration_password_required": "请输入登录密码。",
            "registration_already_pending": "该账号已提交注册申请，请等待超级管理员审批。",
            "registration_not_found": "未找到对应的注册申请。",
            "registration_not_pending": "该注册申请已处理或不存在。",
            "development_login_password_unconfigured": "本地开发登录密码尚未配置，请在运行环境中设置 SMART_DATA_AGENT_DEVELOPMENT_LOGIN_PASSWORD 后重启服务。",
            "analysis_selected_table_semantics_not_registered": "所选数据表尚未登记可执行的字段与指标映射，系统不会改用其他数据源。请在站内数据完成映射后重试，或选择已登记的数据表。",
            "analysis_production_data_table_required": "当前分析没有绑定可执行的数据表。请先在页面选择当前机构的数据表，再发起分析。",
            "analysis_uploaded_media_unsupported": "暂不支持视频、语音类文件。",
            "analysis_uploaded_file_empty": "上传文件是空的，请重新选择文件。",
            "analysis_uploaded_file_too_large": "上传文件不能超过 8MB。",
            "analysis_uploaded_file_unsupported": "暂不支持该文件类型。请上传 Excel、Word、PDF、图片或文本文件。",
            "invalid_content_base64": "文件内容无法解码，请重新上传。",
            "analysis_automation_disabled": "智能分析任务已被管理员停用，请联系机构管理员启用后重试。",
            "automation_task_is_not_active": "智能分析任务当前不可运行，请刷新页面后重试；若仍失败，请联系机构管理员。",
            "supervisor_question_required": "请先输入要发给 Agent 总管的问题。",
            "analysisTaskId is required unless the report has a Topic_Data snapshot.": "请先完成一次分析后再保存。",
            "saved_analysis_visualizations_invalid": "当前图表配置无法保存。请检查图表类型后重试。",
            "saved_analysis_visual_type_invalid": "当前图表类型不受支持，请改用柱状图、表格或文本框后重试。",
            "analysis result id and title are required.": "保存失败：缺少分析结果标题。",
            "result must be an object.": "保存失败：分析结果格式不正确。",
            "report_title_required": "请填写报告标题。",
            "result_id is required.": "缺少要保存的分析结果。",
            "executed_analysis_evidence_required_for_asset_candidate": "当前分析还没有可沉淀的执行证据，无法同步主题表。",
            "topic_table_fields_do_not_match_executed_result": "主题表字段与本次执行结果不一致。",
            "topic_table_uploaded_source_not_persisted": "上传文件分析默认不沉淀主题表。",
            "executed_sql_required_for_topic_table": "当前分析没有可沉淀的 SQL，无法同步主题表。",
            "topic_table_requires_single_executed_query": "主题表只能沉淀单条查询 SQL。",
            "topic_table_sql_must_be_select": "主题表 SQL 必须是查询语句。",
            "topic_table_sql_contains_forbidden_statement": "主题表 SQL 包含不允许的语句。",
            "topic_table_sql_multiple_statements_forbidden": "主题表 SQL 不能包含多条语句。",
            "topic_table_sql_tenant_binding_required": "主题表 SQL 必须绑定当前机构。",
            "customer_segment_list_requires_xlsx": "仅支持 .xlsx 格式的 Excel 客户号名单。",
            "customer_segment_list_size_invalid": "客户号名单不能为空且不得超过 8MB。",
            "customer_segment_list_workbook_invalid": "客户号名单无法解析，请上传未损坏的标准 .xlsx 文件。",
            "customer_segment_list_empty": "Excel 首个工作表的 A 列没有可用客户号。",
            "customer_segment_list_row_limit_exceeded": "客户号名单超过系统上限：最多读取 50,000 行并保留 20,000 个去重客户号。",
            "customer_segment_list_file_name_invalid": "客户号名单文件名无效，请重命名后重新上传。",
            "customer_segment_preview_stale": "文件内容在校验后发生变化，请重新选择文件并校验。",
            "customer_segment_list_metadata_invalid": "客群名单保存信息无效，请重新上传并确认。",
            "customer_segment_list_owner_required": "无法确认客群名单所属用户，请重新登录后再试。",
            "customer_segment_source_customer_key_duplicate": "明细表客户号主键存在重复值，请先修复源数据后再分析。",
            "data_crawler_sql_binding_not_found": "未找到可运行的关联 SQL。请选择 SQL 后点击刷新。",
            "data_crawler_sql_binding_ambiguous": "当前 CSV 对应多条 SQL，请先选择要运行的 SQL 再刷新。",
            "data_crawler_run_id_required": "缺少 Data Crawler 运行记录标识。",
            "non_temporal_sql_parameters_not_supported": "该 SQL 含有非时间参数，暂不能从 SDA 刷新或定时。",
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
        message = validation_messages.get(error_text, "请求未通过校验，请检查后重试。")
        error_code = (
            error_text
            if error_text in {
                "analysis_selected_table_semantics_not_registered",
                "analysis_production_data_table_required",
                "analysis_uploaded_media_unsupported",
                "analysis_uploaded_file_empty",
                "analysis_uploaded_file_too_large",
                "analysis_uploaded_file_unsupported",
                "analysis_automation_disabled",
                "automation_task_is_not_active",
                "login_survey_invalid",
                "login_survey_answers_required",
                "login_survey_answer_too_long",
                "login_survey_identity_required",
                "login_survey_institution_invalid",
                "topic_table_uploaded_source_not_persisted",
                "executed_analysis_evidence_required_for_asset_candidate",
                "customer_segment_list_requires_xlsx",
                "customer_segment_list_size_invalid",
                "customer_segment_list_workbook_invalid",
                "customer_segment_list_empty",
                "customer_segment_list_row_limit_exceeded",
                "customer_segment_list_file_name_invalid",
                "customer_segment_preview_stale",
                "customer_segment_list_metadata_invalid",
                "customer_segment_list_owner_required",
                "customer_segment_source_customer_key_duplicate",
                "data_crawler_sql_binding_not_found",
                "data_crawler_sql_binding_ambiguous",
                "data_crawler_run_id_required",
                "non_temporal_sql_parameters_not_supported",
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
            message = "该手机号或邮箱已绑定其他用户，请直接登录或由管理员授权。"
        if error_text.startswith("用户标识已存在"):
            error_code = "access_user_identity_conflict"
            message = "用户标识已存在，请检查用户账号后重试。"
        if error_text.startswith("机构默认操作员角色不存在"):
            error_code = "access_user_role_not_found"
            message = error_text
        if error_text.startswith("unknown role:"):
            error_code = "access_user_role_not_found"
            message = "角色不存在，请检查机构角色后重试。"
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
        if error_text.startswith("data_asset_missing_field:"):
            error_code = "data_asset_missing_field"
            message = "主题表缺少必填字段，无法同步。"
        if error_text.startswith("data_asset_invalid_identifier:"):
            error_code = "data_asset_invalid_identifier"
            message = "主题表字段名必须是英文字母或下划线开头的标识符。"
        if error_text.startswith("customer_segment_list_value_invalid:"):
            error_code = "customer_segment_list_value_invalid"
            row_number = error_text.split(":", 1)[1] or "未知"
            message = f"Excel A 列第 {row_number} 行不是有效客户号；请改为文本或整数后重新上传。"
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
