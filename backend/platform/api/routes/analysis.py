from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, replace
from http import HTTPStatus
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import uuid4

from backend.platform.bootstrap import PlatformServices
from backend.platform.analysis_workspace.service import (
    build_trusted_manifest,
    provenance_dataset_snapshot,
    provenance_metric_versions,
    safe_cache_key,
)
from backend.platform.analysis_workspace.visualization import VisualizationPlanner
from backend.platform.api.support import send_route_exception
from backend.platform.intelligent_analysis import IntelligentAnalysisEngine
from backend.platform.intelligent_analysis.engine import IntelligentAnalysisRequest
from backend.platform.observability import RuntimeEvent
from backend.platform.repository import serialize_task
from backend.platform.security import validate_read_only_sql_candidate
from backend.platform.settings import require_model_for_application, select_model_for_application
from backend.platform.tenancy import ExecutionContext


ANALYSIS_AUTOMATION_RETRY_POLICY = {"max_attempts": 3, "base_delay_seconds": 2}


def handle_analysis_run(handler: Any) -> None:
    try:
        payload = handler._read_json()
        question = str(payload.get("question") or "").strip()
        if not question:
            handler._send_json({"error": "question_required"}, status=400)
            return
        context = handler._request_context(payload=payload)
        handler.services.permission_broker.require_skill(context.to_execution_context(), "supersonic.query")
        page_context = dict(payload.get("page_context") or {})
        request_id = str(handler.headers.get("Idempotency-Key") or payload.get("request_id") or "").strip()
        if request_id:
            page_context["request_id"] = request_id
        result = run_analysis(
            handler.services,
            user_id=context.user_id,
            tenant_id=context.tenant_id,
            question=question,
            page_context=page_context,
        )
        handler._send_json(result)
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_analysis_run_async(handler: Any) -> None:
    try:
        payload = handler._read_json()
        question = str(payload.get("question") or "").strip()
        if not question:
            raise ValueError("question_required")
        context = handler._request_context(payload=payload)
        handler.services.permission_broker.require_skill(context.to_execution_context(), "supersonic.query")
        page_context = payload.get("page_context") if isinstance(payload.get("page_context"), dict) else {}
        get_param = getattr(handler.services.system_config_store, "get_system_param_value", None)
        analysis_deadline = 900
        analysis_concurrency = 2
        if callable(get_param):
            try:
                analysis_deadline = max(30, min(int(get_param(context.tenant_id, "analysis_deadline_seconds")), 3600))
                analysis_concurrency = max(1, min(int(get_param(context.tenant_id, "analysis_user_concurrency_limit")), 10))
            except (KeyError, TypeError, ValueError):
                pass
        task_code = "system.analysis." + hashlib.sha256(context.user_id.encode("utf-8")).hexdigest()[:20]
        automation_task = handler.services.automation_store.get_task_by_code(context.tenant_id, task_code)
        if automation_task is None:
            automation_task = handler.services.automation_runtime.create_task(
                context.tenant_id,
                {
                    "task_code": task_code,
                    "task_name": "异步智能分析",
                    "task_type": "analysis",
                    "trigger_type": "manual",
                    "handler_ref": "analysis.run",
                    "timeout_seconds": analysis_deadline,
                    "max_concurrency": analysis_concurrency,
                    "retry_policy": ANALYSIS_AUTOMATION_RETRY_POLICY,
                },
                context.user_id,
            )
        elif str(automation_task.get("status") or "").strip() == "disabled":
            # This per-user task is owned by the analysis control plane. A
            # manual user request may resume a paused task, but an explicitly
            # disabled task remains a governance boundary and must fail closed.
            raise ValueError("analysis_automation_disabled")
        elif (
            int(automation_task.get("timeout_seconds") or 0) != analysis_deadline
            or int(automation_task.get("max_concurrency") or 0) != analysis_concurrency
            or dict(automation_task.get("retry_policy") or {}) != ANALYSIS_AUTOMATION_RETRY_POLICY
            or str(automation_task.get("status") or "").strip() == "paused"
        ):
            automation_task = handler.services.automation_runtime.update_task(
                context.tenant_id,
                automation_task["automation_task_id"],
                {
                    "timeout_seconds": analysis_deadline,
                    "max_concurrency": analysis_concurrency,
                    "retry_policy": ANALYSIS_AUTOMATION_RETRY_POLICY,
                    "status": "active",
                },
                context.user_id,
                int(automation_task["lock_version"] if automation_task.get("lock_version") is not None else 1),
            )
        idempotency_key = str(
            handler.headers.get("Idempotency-Key") or payload.get("request_id") or f"analysis-{uuid4().hex}"
        ).strip()
        run = handler.services.automation_runtime.trigger(
            context.tenant_id,
            automation_task["automation_task_id"],
            context.user_id,
            idempotency_key,
            {"question": question, "page_context": page_context, "request_id": idempotency_key},
        )
        handler._write_audit(
            context,
            "analysis.run.enqueue",
            "automation_run",
            run["automation_run_id"],
            {"status": run["status"], "task_id": automation_task["automation_task_id"]},
        )
        handler._send_json(
            {"tenant_id": context.tenant_id, "run": run, "poll_path": "/api/analysis/run-status"},
            HTTPStatus.ACCEPTED,
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_analysis_task_get(handler: Any, query: str) -> None:
    from urllib.parse import parse_qs

    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        task_id = str((params.get("task_id") or [""])[0]).strip()
        task = handler.services.task_repository.get_task(task_id)
        if not task:
            raise KeyError("analysis_task_not_found")
        if task.get("tenant_id") != context.tenant_id or task.get("user_id") != context.user_id:
            raise PermissionError("Analysis task is unavailable.")
        handler._send_json({"tenant_id": context.tenant_id, "task": _decorate_analysis_payload(task)})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_analysis_history_get(handler: Any, query: str) -> None:
    from urllib.parse import parse_qs

    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        task_id = str((params.get("task_id") or [""])[0]).strip()
        if task_id:
            task = handler.services.task_repository.get_task(task_id)
            if not task or task.get("tenant_id") != context.tenant_id or task.get("user_id") != context.user_id:
                raise PermissionError("Analysis task is unavailable.")
            trace_id = str(task.get("trace_id") or "")
            read_spans = getattr(handler.services.task_repository, "trace_spans", None)
            spans = read_spans(trace_id) if trace_id and callable(read_spans) else []
            handler._send_json({
                "tenant_id": context.tenant_id,
                "task": _decorate_analysis_payload(task),
                "spans": spans,
            })
            return
        limit = max(1, min(int((params.get("limit") or ["50"])[0]), 100))
        tasks = handler.services.task_repository.list_tasks(context.tenant_id, context.user_id, limit)
        handler._send_json({
            "tenant_id": context.tenant_id,
            "tasks": [_decorate_analysis_payload(task) for task in tasks],
            "count": len(tasks),
        })
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_analysis_history_delete(handler: Any, query: str) -> None:
    from urllib.parse import parse_qs

    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        task_id = str((params.get("task_id") or [""])[0]).strip()
        if not task_id:
            raise ValueError("task_id is required")
        deleted = handler.services.task_repository.delete_task(
            context.tenant_id,
            context.user_id,
            task_id,
        )
        if not deleted:
            raise KeyError("analysis_task_not_found")
        handler._write_audit(
            context,
            "analysis.history.delete",
            "analysis_task",
            task_id,
            {"owner_user_id": context.user_id},
        )
        handler._send_json({"tenant_id": context.tenant_id, "task_id": task_id, "deleted": True})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_analysis_run_status(handler: Any, query: str) -> None:
    from urllib.parse import parse_qs

    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler.services.permission_broker.require_skill(context.to_execution_context(), "supersonic.query")
        run_id = str((params.get("run_id") or [""])[0]).strip()
        if not run_id:
            raise ValueError("run_id is required")
        run = handler.services.automation_store.get_run(context.tenant_id, run_id)
        if str(run.get("created_by") or "") != context.user_id:
            raise PermissionError("Analysis run is unavailable.")
        list_steps = getattr(handler.services.automation_store, "list_steps", None)
        run["progress_steps"] = list_steps(context.tenant_id, run_id) if callable(list_steps) else []
        handler._send_json({"tenant_id": context.tenant_id, "run": run})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_analysis_run_cancel(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler.services.permission_broker.require_skill(context.to_execution_context(), "supersonic.query")
        run_id = str(payload.get("automation_run_id") or payload.get("run_id") or "").strip()
        if not run_id:
            raise ValueError("run_id is required")
        run = handler.services.automation_store.cancel_run(context.tenant_id, run_id, context.user_id)
        handler._write_audit(
            context,
            "analysis.run.cancel",
            "automation_run",
            run_id,
            {"status": run["status"]},
        )
        handler._send_json({"tenant_id": context.tenant_id, "run": run})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def run_analysis(
    services: PlatformServices,
    user_id: str,
    tenant_id: str,
    question: str,
    page_context: dict[str, Any] | None = None,
    cancellation_check: Any | None = None,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    current_progress: tuple[str, int, str] | None = None

    def progress(
        step_code: str,
        sequence_no: int,
        status: str,
        label: str,
        detail: str,
        refs: dict[str, Any] | None = None,
    ) -> None:
        nonlocal current_progress
        if status == "running":
            current_progress = (step_code, sequence_no, label)
        elif current_progress and current_progress[0] == step_code:
            current_progress = None
        if callable(progress_callback):
            progress_callback(step_code, sequence_no, status, label, detail, refs)

    progress("context_understanding", 10, "running", "理解问题与装载上下文", "正在识别机构、业务问题、技能、文件和已选数据表。")
    requested_context = dict(page_context or {})
    requested_context = _resolve_analysis_extensions(services, tenant_id, requested_context)
    request_id = str(requested_context.get("request_id") or "").strip()
    if request_id:
        existing = services.task_repository.get_task_by_request(tenant_id, request_id)
        if existing:
            if existing.get("user_id") != user_id:
                raise PermissionError("Idempotency key belongs to another user.")
            return _decorate_analysis_payload(existing)

    visual_scope = _visual_analysis_scope(requested_context)
    requested_context["visual_analysis_scope"] = visual_scope
    parent: dict[str, Any] | None = None
    if visual_scope == "page":
        requested_context["chart_bound_source"] = False
        requested_context.pop("parent_task_id", None)
        requested_context.pop("parent_execution_id", None)
        source_tables = _visual_analysis_source_tables(requested_context)
        if source_tables:
            requested_context["selected_data_tables"] = source_tables
    else:
        explicit_parent_task_id = str(requested_context.get("parent_task_id") or "").strip()
        parent_task_id = _chart_follow_up_parent_task_id(requested_context)
        if parent_task_id:
            parent = services.task_repository.get_task(parent_task_id)
            if not parent or parent.get("tenant_id") != tenant_id or parent.get("user_id") != user_id:
                if explicit_parent_task_id:
                    raise PermissionError("Parent analysis execution is unavailable.")
                parent = None
            else:
                requested_context["parent_task_id"] = parent_task_id
                requested_context["parent_execution_id"] = str(parent.get("execution_id") or parent.get("task_id") or "")
                requested_context["revision"] = int(parent.get("revision") or 1) + 1
        requested_context = _inherit_chart_follow_up_context(requested_context, parent)
    planning_question = _visual_follow_up_planning_question(requested_context, question)
    if planning_question != question:
        requested_context["analysis_planning_question"] = planning_question

    trace_id = services.trace_recorder.start_trace()
    started_at = perf_counter()
    reused_visual, reused_plan = _take_reused_visual(
        services,
        tenant_id,
        user_id,
        requested_context,
        parent,
        visual_scope,
    )
    catalog_failed: Exception | None = None
    try:
        asset_context = _build_asset_context(
            services,
            tenant_id,
            planning_question,
            requested_context,
            user_id=user_id,
        )
    except PermissionError as exc:
        catalog_failed = exc
        if reused_visual is None:
            if str(exc) == "selected_data_asset_not_published_or_not_authorized":
                progress(
                    "context_understanding",
                    10,
                    "failed",
                    "理解问题与装载上下文",
                    "所选数据表已更新、下线或不属于当前机构，请重新选择数据表后重试。",
                )
            raise
        asset_context = _reused_visual_asset_context(requested_context, parent)
    catalog_tables = _list_of_dicts(asset_context.get("selected_data_tables") if isinstance(asset_context, dict) else [])
    use_reused_visual = reused_visual is not None and (
        visual_scope == "page"
        or not catalog_tables
        or catalog_failed is not None
        or _selected_raw_tables_conflict(asset_context)
    )
    if not use_reused_visual:
        if _selected_table_requires_semantic_registration(asset_context):
            if reused_visual is not None:
                use_reused_visual = True
                asset_context = _reused_visual_asset_context(requested_context, parent)
            else:
                raise ValueError("analysis_selected_table_semantics_not_registered")
        elif _requires_selected_production_source(services, requested_context, asset_context):
            raise ValueError("analysis_production_data_table_required")
    context = ExecutionContext(
        user_id=user_id,
        tenant_id=tenant_id,
        page_context={
            "trace_id": trace_id,
            **requested_context,
            "asset_context": asset_context,
        },
    )
    workspace_binding = _validate_workspace_binding(
        services,
        tenant_id=tenant_id,
        user_id=user_id,
        requested_context=requested_context,
    )
    services.trace_recorder.add_span(
        "api.analysis.start",
        inputs={"tenant_id": tenant_id, "user_id": user_id, "question_length": len(question)},
    )
    task = services.workflow.create_task(context, question)
    try:
        _raise_if_cancelled(cancellation_check)
        _prepare_manual_revision(services, context.page_context, parent, task)
        selected_model = _resolve_selected_model(services, tenant_id, requested_context, user_id=user_id)
        asset_context = context.page_context.get("asset_context", {})
        cache_context = _analysis_cache_context(
            services,
            user_id=user_id,
            tenant_id=tenant_id,
            question=question,
            requested_context=requested_context,
            asset_context=asset_context if isinstance(asset_context, dict) else {},
            selected_model=selected_model,
        )
        if cache_context is not None and not request_id and parent is None:
            services.permission_broker.require_skill(context, "supersonic.query")
            cached = services.analysis_governance_store.get_cache(
                tenant_id,
                user_id,
                cache_context["cache_key"],
                cache_context["authorization_hash"],
            )
            if cached:
                cached_task = services.task_repository.get_task(str(cached.get("result_ref") or ""))
                if cached_task and cached_task.get("tenant_id") == tenant_id and cached_task.get("user_id") == user_id:
                    progress("context_understanding", 10, "succeeded", "理解问题与装载上下文", "已完成权限、数据快照与语义版本复核。")
                    progress("result_finalize", 60, "succeeded", "复用可信分析结果", "已命中同权限、同数据与同语义版本的可信结果。")
                    cached_payload = {
                        **_decorate_analysis_payload(cached_task),
                        "cache_hit": True,
                        "cache_key": cache_context["cache_key"],
                        "cache_generated_at": str(cached.get("updated_at") or cached.get("created_at") or ""),
                    }
                    workspace_turn = _append_workspace_analysis_turn(
                        services,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        question=question,
                        binding=workspace_binding,
                        payload=cached_payload,
                    )
                    if workspace_turn is not None:
                        cached_payload["workspace_turn"] = workspace_turn
                    return cached_payload
        progress(
            "context_understanding",
            10,
            "succeeded",
            "理解问题与装载上下文",
            "已完成上下文装载并确定分析范围。",
            {
                "selected_table_count": len(_list_of_dicts(asset_context.get("selected_data_tables"))) if isinstance(asset_context, dict) else 0,
                "skill_count": len(_list_of_dicts(requested_context.get("analysis_context_skills"))),
            },
        )
        intelligent_engine = IntelligentAnalysisEngine()
        planning_result: dict[str, Any] = {}
        use_skill_solution_plan = any(
            str(skill.get("analysisMethod") or "").strip()
            for skill in _list_of_dicts(requested_context.get("analysis_context_skills"))
        )
        analysis_policy = _dict_or_empty(requested_context.get("analysis_policy"))
        data_first_mode = str(analysis_policy.get("resultDelivery") or analysis_policy.get("result_delivery") or "") == "data_first"

        def selected_model_planning_hook(server_plan: dict[str, Any]) -> dict[str, Any]:
            nonlocal planning_result
            planning_result = intelligent_engine.plan(
                IntelligentAnalysisRequest(
                    question=question,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    analysis_plan=server_plan,
                    asset_context=context.page_context.get("asset_context", {}),
                    skill=_dict_or_none(requested_context.get("analysis_skill")),
                    skills=_list_of_dicts(requested_context.get("analysis_context_skills")),
                    model=selected_model,
                    plugins=_list_of_dicts(requested_context.get("plugins")),
                    files=_list_of_dicts(requested_context.get("files")),
                    conversation_context=_dict_or_empty(requested_context.get("conversation_session")),
                    analysis_trigger=str(requested_context.get("analysis_trigger") or "manual"),
                    voice_silence_ms=int(_dict_or_empty(requested_context.get("realtime_voice_auto_analysis")).get("silenceMs") or 5000),
                    context_policy=_dict_or_empty(requested_context.get("analysis_policy")),
                    surface_context=requested_context,
                )
            )
            progress(
                "model_planning",
                20,
                "succeeded",
                "生成分析方案",
                "已生成指标、维度、查询与可视化方案。",
                {
                    "metric_count": len(planning_result.get("metrics") or []),
                    "dimension_count": len(planning_result.get("dimensions") or []),
                },
            )
            progress("data_query", 30, "running", "查询业务数据", "正在执行受权限控制的语义查询并获取明细数据。")
            return planning_result

        if selected_model and not use_skill_solution_plan and not data_first_mode and not use_reused_visual:
            progress("model_planning", 20, "running", "生成分析方案", "正在将问题转换为指标、维度、查询和可视化方案。")
        else:
            planning_source = "当前页面可视化数据" if visual_scope == "page" else "当前图表已查询数据"
            progress("model_planning", 20, "skipped", "生成分析方案", f"已使用{planning_source}，先查询数据并减少一次模型等待。" if not use_reused_visual else "已复用当前可视化绑定的查询结果，不再重新选表。")
            progress("data_query", 30, "running", "查询业务数据", "正在执行受权限控制的语义查询并获取明细数据。" if not use_reused_visual else "正在装载当前可视化已绑定的数据。")
        if use_reused_visual and reused_visual is not None:
            if reused_plan:
                task.analysis_plan = dict(reused_plan)
            query_result = dict(reused_visual)
            query_result.pop("intelligent_analysis", None)
            query_result.pop("_analysis_plan", None)
            task.skill_results = [query_result]
        else:
            task = services.workflow.run(
                context,
                question,
                task=task,
                planning_hook=selected_model_planning_hook if selected_model and not use_skill_solution_plan and not data_first_mode else None,
            )
            query_result = dict(task.skill_results[0]) if task.skill_results else {}
        _raise_if_cancelled(cancellation_check)
        task.trace_id = services.trace_recorder.trace_id
        if not query_result and task.skill_results:
            query_result = dict(task.skill_results[0])
        if query_result:
            query_result["semantic_info"] = _enrich_query_provenance(
                query_result.get("semantic_info"),
                requested_context=requested_context,
                asset_context=asset_context if isinstance(asset_context, dict) else {},
                parent=parent,
                result_rows=_list_of_dicts(query_result.get("data")),
            )
            query_result["evidence"] = _build_execution_evidence(query_result)
            analysis_plan = task.analysis_plan if isinstance(task.analysis_plan, dict) else {}
            chart_spec = query_result.get("chart_spec") if isinstance(query_result.get("chart_spec"), dict) else {}
            chart_rows = _list_of_dicts(query_result.get("data"))
            chart_metrics = _string_list(analysis_plan.get("metrics"))
            chart_dimensions = _string_list(analysis_plan.get("dimensions"))
            if not chart_metrics or not chart_dimensions:
                inferred_metrics, inferred_dimensions = _infer_chart_fields(chart_rows)
                chart_metrics = chart_metrics or inferred_metrics
                chart_dimensions = chart_dimensions or inferred_dimensions
            query_result["visualization_spec"] = VisualizationPlanner().plan(
                question=question,
                rows=chart_rows,
                dimensions=chart_dimensions,
                metrics=chart_metrics,
                intent=analysis_plan,
                proposed_chart_types=_string_list([chart_spec.get("type")]),
                requested_chart_types=_string_list(_dict_or_empty(requested_context.get("visualization_preferences")).get("chart_types")),
            ).payload()
            task.skill_results[0] = query_result
            services.workflow.enrich_with_data_product_skills(context, task, question)
            query_result = dict(task.skill_results[0])
        task.trace_id = services.trace_recorder.trace_id
        services.task_repository.save_task(task)
        row_count = len(query_result.get("data") or []) if isinstance(query_result, dict) else 0
        progress(
            "data_query",
            30,
            "succeeded",
            "查询业务数据",
            (
                "已返回 0 行结果，当前没有可分析数据；将跳过模型结论，避免无效等待。"
                if row_count == 0
                else f"已返回 {row_count} 行结果，可先查看数据与可视化；模型将继续生成结论。"
            ),
            {"row_count": row_count, "partial_task_id": task.task_id},
        )
        progress("evidence_review", 40, "running", "校验口径与证据", "正在核对指标口径、权限证据、SQL 与返回字段。")
        progress(
            "evidence_review",
            40,
            "succeeded",
            "校验口径与证据",
            "查询证据已绑定，结果可追溯到数据源快照与执行 SQL。",
        )
        final_request = IntelligentAnalysisRequest(
                question=question,
                tenant_id=tenant_id,
                user_id=user_id,
                analysis_plan=task.analysis_plan,
                asset_context=context.page_context.get("asset_context", {}),
                skill=_dict_or_none(requested_context.get("analysis_skill")),
                skills=_list_of_dicts(requested_context.get("analysis_context_skills")),
                model=selected_model,
                plugins=_list_of_dicts(requested_context.get("plugins")),
                files=_list_of_dicts(requested_context.get("files")),
                conversation_context=_dict_or_empty(requested_context.get("conversation_session")),
                analysis_trigger=str(requested_context.get("analysis_trigger") or "manual"),
                voice_silence_ms=int(_dict_or_empty(requested_context.get("realtime_voice_auto_analysis")).get("silenceMs") or 5000),
                context_policy=_dict_or_empty(requested_context.get("analysis_policy")),
                surface_context=requested_context,
                query_result=query_result,
            )
        if not planning_result:
            planning_result = intelligent_engine.plan(
                replace(final_request, model=None) if use_skill_solution_plan or data_first_mode else final_request
            )
            if use_skill_solution_plan or data_first_mode:
                planning_result["planning_invocation"] = {
                    "status": "skipped",
                    "callable": False,
                    "message": (
                        "已使用服务端快速语义方案先返回查询数据，跳过重复的大模型规划调用。"
                        if data_first_mode
                        else "已使用管理员维护的 Skill 解决方案和服务端语义计划，跳过重复的大模型规划调用。"
                    ),
                    "prompt_template_id": "data_first.server_plan.v1" if data_first_mode else "skill_solution.server_plan.v1",
                }
        brief_follow_up = _is_rail_brief_context(requested_context)
        if row_count == 0:
            progress("model_conclusion", 50, "skipped", "生成分析结论", "实际查询返回 0 行，跳过无数据情况下的模型结论调用。")
        elif brief_follow_up:
            progress("model_conclusion", 50, "running", "归纳数据结论", "正在用两三句话概括当前图表数据。")
        else:
            progress("model_conclusion", 50, "running", "生成分析结论", "正在基于已执行的数据证据归纳发现、原因边界与建议。")
        intelligent_analysis = intelligent_engine.analyze(
            final_request,
            planning_result,
        )
        if row_count != 0:
            progress(
                "model_conclusion",
                50,
                "succeeded",
                "归纳数据结论" if brief_follow_up else "生成分析结论",
                "已生成短结论并配一张聚焦图表。" if brief_follow_up else "已生成基于实际查询证据的分析摘要与关键发现。",
                {"finding_count": len(intelligent_analysis.get("metric_findings") or [])},
            )
        _raise_if_cancelled(cancellation_check)
        if task.skill_results:
            task.skill_results[0] = {
                **task.skill_results[0],
                "intelligent_analysis": intelligent_analysis,
            }
        task.conclusions = intelligent_analysis["possible_conclusions"] + task.conclusions
        progress("result_finalize", 60, "running", "整理可视化结果", "正在完成图表配置、结论复核和结果发布检查。")
        services.workflow.finalize(context, task, intelligent_analysis)
        if task.skill_results:
            first_result = dict(task.skill_results[0])
            evidence = _dict_or_empty(first_result.get("evidence"))
            semantic = _dict_or_empty(first_result.get("semantic_info"))
            visualization = _dict_or_empty(first_result.get("visualization_spec"))
            selected_model_id = str(_dict_or_empty(selected_model).get("id") or _dict_or_empty(selected_model).get("model") or "")
            skill_versions = [
                {"skill_id": str(item.get("id") or ""), "version": str(item.get("version") or item.get("assetVersion") or "pinned")}
                for item in _list_of_dicts(requested_context.get("analysis_context_skills"))
                if str(item.get("id") or "")
            ]
            follow_up_values = _visual_follow_up_values(requested_context)
            first_result["trusted_manifest"] = build_trusted_manifest(
                tenant_id=tenant_id,
                artifact_id=str(task.execution_id or task.task_id),
                dataset_snapshot=provenance_dataset_snapshot(
                    semantic.get("source_snapshot"),
                    evidence.get("source_snapshot"),
                    requested_context.get("dataset_snapshot"),
                    follow_up_values.get("dataset_snapshot"),
                    *(_list_of_dicts(asset_context.get("selected_data_tables")) if isinstance(asset_context, dict) else []),
                    *_list_of_dicts(follow_up_values.get("selected_data_tables")),
                    schema_material=[semantic.get("schema_mapping"), first_result.get("data")],
                    content_material=first_result.get("data") or [],
                ),
                metric_versions=provenance_metric_versions(
                    semantic.get("metric_versions"),
                    evidence.get("metric_versions"),
                    asset_context.get("metric_dictionary_definitions") if isinstance(asset_context, dict) else [],
                ),
                sql=str(evidence.get("executed_sql") or first_result.get("sql") or ""),
                result=first_result.get("data") or [],
                visualization=visualization,
                skill_versions=skill_versions,
                model_version=selected_model_id,
                authorization_snapshot=_analysis_authorization_snapshot(
                    services,
                    tenant_id=tenant_id,
                    user_id=user_id,
                ) or _dict_or_empty(semantic.get("metric_access")),
                evidence_refs=[evidence] if evidence else [],
                evaluation=task.review if isinstance(task.review, dict) else {},
            )
            task.skill_results[0] = first_result
        payload = serialize_task(task)
        payload["asset_context"] = context.page_context.get("asset_context", {})
        payload["intelligent_analysis"] = intelligent_analysis
        fallback_used = _fallback_used(payload)
        latency_ms = _elapsed_ms(started_at)
        services.trace_recorder.add_span(
            "api.analysis.finish",
            outputs={
                "task_id": task.task_id,
                "latency_ms": latency_ms,
                "fallback_used": fallback_used,
                "status": "ok",
            },
        )
        services.task_repository.save_task(task)
        if cache_context is not None and _cache_snapshot_matches(cache_context, task):
            services.analysis_governance_store.put_cache(
                tenant_id,
                user_id,
                {
                    **cache_context,
                    "result_ref": task.task_id,
                },
                ttl_seconds=int(requested_context.get("cache_ttl_seconds") or 900),
            )
        services.lineage_store.record_analysis(payload)
        topic_data_references = services.topic_data_store.record_analysis_execution(
            tenant_id=tenant_id,
            user_id=user_id,
            task=payload,
            source_reference=_dict_or_none(requested_context.get("topic_data_source")),
        )
        payload["topic_data"] = topic_data_references
        workspace_turn = _append_workspace_analysis_turn(
            services,
            tenant_id=tenant_id,
            user_id=user_id,
            question=question,
            binding=workspace_binding,
            payload=payload,
        )
        if workspace_turn is not None:
            payload["workspace_turn"] = workspace_turn
        services.task_repository.save_runtime_event(
            RuntimeEvent(
                event_type="analysis.run",
                trace_id=trace_id,
                tenant_id=tenant_id,
                user_id=user_id,
                status="ok",
                latency_ms=latency_ms,
                fallback_used=fallback_used,
                detail={
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                    "semantic_client_mode": services.semantic_client_mode,
                },
            )
        )
        services.task_repository.save_trace_spans(services.trace_recorder.spans())
        progress(
            "result_finalize",
            60,
            "succeeded",
            "整理可视化结果",
            "分析结果、可视化与思考阶段已全部就绪。",
            {"task_id": task.task_id, "publishable": task.status == "completed"},
        )
        return payload
    except Exception as exc:
        if current_progress:
            step_code, sequence_no, label = current_progress
            progress(step_code, sequence_no, "failed", label, "该阶段执行失败，请查看稳定错误码或执行记录后重试。")
        latency_ms = _elapsed_ms(started_at)
        was_cancelled = str(exc) == "analysis_cancelled"
        task.trace_id = trace_id
        task.status = "cancelled" if was_cancelled else "failed"
        task.review = {
            "status": "cancelled" if was_cancelled else "failed",
            "error_code": "analysis_cancelled" if was_cancelled else "analysis_execution_failed",
            "checks": {},
            "publication_gate": "blocked",
        }
        services.trace_recorder.add_span(
            "api.analysis.error",
            outputs={
                "latency_ms": latency_ms,
                "error_type": type(exc).__name__,
                "message": "analysis_cancelled" if was_cancelled else "analysis_execution_failed",
            },
            status="cancelled" if was_cancelled else "error",
        )
        services.task_repository.save_runtime_event(
            RuntimeEvent(
                event_type="analysis.run",
                trace_id=trace_id,
                tenant_id=tenant_id,
                user_id=user_id,
                status="cancelled" if was_cancelled else "error",
                latency_ms=latency_ms,
                fallback_used=False,
                detail={
                    "error_type": type(exc).__name__,
                    "message": "analysis_cancelled" if was_cancelled else "analysis_execution_failed",
                    "semantic_client_mode": services.semantic_client_mode,
                },
            )
        )
        services.task_repository.save_task(task)
        services.task_repository.save_trace_spans(services.trace_recorder.spans())
        raise


def _raise_if_cancelled(cancellation_check: Any | None) -> None:
    if callable(cancellation_check) and bool(cancellation_check()):
        raise RuntimeError("analysis_cancelled")


def _resolve_analysis_extensions(
    services: PlatformServices,
    tenant_id: str,
    page_context: dict[str, Any],
) -> dict[str, Any]:
    """Resolve client-selected Skill IDs against tenant-governed assets.

    The browser may choose IDs, but it cannot author the memory, tool, format or
    strategy content that enters a model prompt. Knowledge files are extraction
    inputs only and can never be resolved as Skill memories.
    """

    store = getattr(services, "data_asset_store", None)
    if store is None:
        return page_context
    try:
        bundle = store.list_published_bundle(tenant_id)
    except Exception:
        return page_context
    skill_by_id = {
        str(item.get("id") or ""): item
        for item in bundle.get("analysis_skills", [])
        if isinstance(item, dict) and item.get("enabled") is not False
    }
    tool_by_id = {
        str(item.get("id") or ""): item
        for item in bundle.get("external_tools", [])
        if isinstance(item, dict) and item.get("enabled") is True
    }
    memory_by_id = {
        str(item.get("id") or ""): item
        for item in [
            *bundle.get("intents", []),
            *bundle.get("analysis_experiences", []),
            *bundle.get("behavior_habits", []),
        ]
        if isinstance(item, dict)
    }
    requested = _list_of_dicts(page_context.get("analysis_context_skills"))
    selected = _dict_or_none(page_context.get("analysis_skill"))
    if selected:
        requested.insert(0, selected)
    resolved: list[dict[str, Any]] = []
    seen: set[str] = set()
    legacy_skill_ids = {
        "weekly-report": "scene-weekly-report", "daily-operation": "scene-daily-operation",
        "risk-strategy": "scene-risk-strategy", "descriptive": "topic-descriptive",
        "attribution": "topic-attribution", "forecast": "topic-predictive",
        "exploratory": "topic-exploratory", "budget": "topic-financial-budget",
        "credit-risk": "topic-credit-risk", "suspicious-transaction": "topic-suspicious-transaction",
        "liquidity-risk": "topic-liquidity-risk", "overdue-risk": "topic-overdue-risk",
    }
    page_skills = {
        "page-funnel": ("业务漏斗页面追问", "基于当前漏斗筛选和重新执行的数据证据识别阶段断点。"),
        "page-sandbox": ("经营沙盘页面追问", "基于当前经营筛选与受治理基线分析趋势；未执行的模拟参数不得视为事实。"),
        "page-supervision": ("机构督导页面追问", "基于当前机构、产品筛选和重新执行的数据证据形成督导分析。"),
        "page-customers": ("客群分析页面追问", "基于当前机构、产品和客群筛选分析规模与转化。"),
        "page-competition": ("竞品分析页面追问", "基于当前产品视图与已授权市场观测进行对标分析。"),
        "page-email-daily": ("邮件日报页面追问", "复核当前日报来源版本、发布门禁和投递状态。"),
        "page-my-reports": ("我的报告页面追问", "基于当前报告快照和重新执行的证据继续分析。"),
        "page-metric-management": ("指标管理页面追问", "基于当前指标语义版本检查口径和影响范围。"),
        "page-data-management": ("数据管理页面追问", "基于当前数据资产版本检查 Schema、语义关系和影响范围。"),
        "page-weekly-core": ("经营周报三指标结论", "基于当前机构已载入的周报三指标和重新执行的数据证据形成结论，不依赖其他机构的 Skill 目录。"),
    }
    for reference in requested[:12]:
        skill_id = str(reference.get("id") or "").strip()
        if not skill_id or skill_id in seen:
            continue
        configured = skill_by_id.get(skill_id) or skill_by_id.get(legacy_skill_ids.get(skill_id, ""))
        if configured is None:
            if skill_id in page_skills:
                name, description = page_skills[skill_id]
                configured = {
                    "id": skill_id,
                    "name": name,
                    "category": "场景",
                    "description": description,
                }
            elif str(reference.get("category") or "") != "模式":
                continue
            else:
                configured = {
                    "id": skill_id,
                    "name": str(reference.get("name") or "")[:120],
                    "category": "模式",
                    "description": str(reference.get("description") or "")[:500],
                }
        seen.add(skill_id)
        memory_refs = _string_list(configured.get("memoryRefs"))
        tool_refs = _string_list(configured.get("toolRefs"))
        resolved_skill = {
            key: configured.get(key)
            for key in (
                "id", "name", "category", "description", "analysisMethod", "documentAbstraction",
                "outputFormat", "viewpointStrategy", "recommendedSkillIds",
            )
            if configured.get(key) not in (None, "")
        } | {
            "memoryRefs": memory_refs,
            "toolRefs": tool_refs,
            "memories": [
                _bounded_extension_asset(memory_by_id[memory_id])
                for memory_id in memory_refs
                if memory_id in memory_by_id
            ][:12],
            "tools": [
                _bounded_extension_asset(tool_by_id[tool_id])
                for tool_id in tool_refs
                if tool_id in tool_by_id
            ][:12],
        }
        if str(configured.get("category") or "") == "主题":
            resolved_skill.pop("outputFormat", None)
        resolved.append(resolved_skill)
    resolved_ids = {str(item.get("id") or "") for item in resolved}
    selected_id = str((selected or {}).get("id") or "")
    selected_id = legacy_skill_ids.get(selected_id, selected_id)
    plugins = {
        str(tool.get("id") or ""): tool
        for skill in resolved
        for tool in skill.get("tools", [])
        if isinstance(tool, dict)
    }
    return {
        **page_context,
        "analysis_context_skills": resolved,
        "analysis_skill": next((item for item in resolved if item.get("id") == selected_id), None),
        "plugins": list(plugins.values()),
        "resolved_analysis_skill_ids": sorted(resolved_ids),
    }


def _bounded_extension_asset(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in item.items()
        if key not in {"lockVersion", "submittedBy", "reviewedBy"}
        and isinstance(value, (str, int, float, bool, list, dict, type(None)))
    }


def _decorate_analysis_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    skill_results = result.get("skill_results") if isinstance(result.get("skill_results"), list) else []
    first = skill_results[0] if skill_results and isinstance(skill_results[0], dict) else {}
    intelligent = first.get("intelligent_analysis") if isinstance(first.get("intelligent_analysis"), dict) else {}
    result.setdefault("intelligent_analysis", intelligent)
    result.setdefault("asset_context", intelligent.get("context", {}).get("asset_context", {}) if intelligent else {})
    result["idempotent_replay"] = True
    return result


def _prepare_manual_revision(
    services: PlatformServices,
    page_context: dict[str, Any],
    parent: dict[str, Any] | None,
    task: Any,
) -> None:
    edited_sql = _strip_display_parameters(str(page_context.get("edited_sql_script") or ""))
    edited_python = str(page_context.get("edited_python_script") or "").strip()
    edited_plan = page_context.get("edited_analysis_plan")
    edited_summary = str(page_context.get("edited_ai_summary") or "").strip()
    if not any((edited_sql, edited_python, edited_plan, edited_summary)):
        return
    if not parent:
        raise ValueError("manual_revision_requires_parent_execution")

    parent_results = parent.get("skill_results") if isinstance(parent.get("skill_results"), list) else []
    parent_result = parent_results[0] if parent_results and isinstance(parent_results[0], dict) else {}
    previous_sql = str(parent_result.get("sql") or "").strip()
    previous_python = str(parent_result.get("python_script") or "").strip()
    manual_edits: dict[str, Any] = {}
    if edited_sql:
        if edited_sql == previous_sql:
            manual_edits["sql"] = {"status": "unchanged"}
        else:
            validated_sql = validate_read_only_sql_candidate(edited_sql)
            page_context["manual_sql_candidate"] = validated_sql
            page_context["query_revision"] = task.revision
            manual_edits["sql"] = {
                "status": "accepted_for_governed_recompile",
                "candidate_sha256": hashlib.sha256(validated_sql.encode("utf-8")).hexdigest(),
            }
    if edited_python:
        if edited_python == previous_python:
            manual_edits["python"] = {"status": "unchanged"}
        else:
            services.workflow.python_sandbox.validate_code(edited_python)
            page_context["manual_python_script"] = edited_python
            manual_edits["python"] = {
                "status": "accepted_for_sandbox_execution",
                "candidate_sha256": hashlib.sha256(edited_python.encode("utf-8")).hexdigest(),
            }
    if edited_plan:
        manual_edits["plan"] = {
            "status": "annotation_only",
            "reason": "free_text_plan_is_not_an_executable_typed_revision",
        }
    if edited_summary:
        manual_edits["summary"] = {
            "status": "annotation_only",
            "candidate_sha256": hashlib.sha256(edited_summary.encode("utf-8")).hexdigest(),
        }
    task.manual_edits = manual_edits


def _strip_display_parameters(value: str) -> str:
    marker = "\n\n-- Parameters\n"
    return value.split(marker, 1)[0].strip() if marker in value else value.strip()


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))


def _fallback_used(payload: dict[str, Any]) -> bool:
    for result in payload.get("skill_results", []):
        semantic_info = result.get("semantic_info", {}) if isinstance(result, dict) else {}
        if semantic_info.get("fallback"):
            return True
    return False


def _build_execution_evidence(result: dict[str, Any]) -> dict[str, Any]:
    execution_statement = str(result.get("sql") or "").strip()
    data = result.get("data") if isinstance(result.get("data"), list) else []
    semantic_info = result.get("semantic_info") if isinstance(result.get("semantic_info"), dict) else {}
    sql_executed = bool(semantic_info.get("sql_executed", True))
    executed_sql = execution_statement if sql_executed else ""
    data_source = str(semantic_info.get("data_source") or "unknown")
    execution_mode = str(semantic_info.get("execution_mode") or "").strip().lower()
    mock_mode = execution_mode == "mock" or (not execution_mode and "mock" in data_source.lower())
    parameters = result.get("parameters") if isinstance(result.get("parameters"), dict) else {}
    evidence_material = {
        "sql_sha256": hashlib.sha256(executed_sql.encode("utf-8")).hexdigest() if executed_sql else "",
        "parameters": parameters,
        "rows": data,
        "dataset_id": semantic_info.get("dataset_id"),
        "source_snapshot": semantic_info.get("source_snapshot"),
        "metric_definition_versions": semantic_info.get("metric_definition_versions"),
    }
    evidence_id = "ev_" + hashlib.sha256(
        json.dumps(evidence_material, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "evidence_id": evidence_id,
        "executed_sql": executed_sql,
        "execution_statement": execution_statement,
        "sql_executed": sql_executed,
        "executed_sql_sha256": hashlib.sha256(executed_sql.encode("utf-8")).hexdigest() if executed_sql else "",
        "row_count": len(data),
        "dataset_id": str(semantic_info.get("dataset_id") or ""),
        "data_source": data_source,
        "data_mode": "mock" if mock_mode else "real",
        "publishable": bool(semantic_info.get("publishable", not mock_mode)),
        "connection_id": str(semantic_info.get("connection_id") or ""),
        "provider_query_id": str(semantic_info.get("provider_query_id") or ""),
        "policy_enforced_at_source": bool(semantic_info.get("policy_enforced_at_source")),
        "parameters": parameters,
        "totals": semantic_info.get("totals") if isinstance(semantic_info.get("totals"), dict) else {},
        "source_snapshot": semantic_info.get("source_snapshot") if isinstance(semantic_info.get("source_snapshot"), dict) else {},
        "aggregation_semantics_complete": bool(semantic_info.get("aggregation_semantics_complete")),
        "metric_definitions_bound": bool(semantic_info.get("metric_definitions_bound")),
        "metric_definition_versions": semantic_info.get("metric_definition_versions")
        if isinstance(semantic_info.get("metric_definition_versions"), dict)
        else {},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _chart_follow_up_parent_task_id(requested_context: dict[str, Any]) -> str:
    parent_task_id = str(requested_context.get("parent_task_id") or "").strip()
    if parent_task_id:
        return parent_task_id
    point = _dict_or_empty(requested_context.get("selected_data_point"))
    values = _dict_or_empty(point.get("values"))
    return str(values.get("analysis_task_id") or "").strip()


def _parent_visual_query_result(parent: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(parent, dict):
        return None
    results = parent.get("skill_results") if isinstance(parent.get("skill_results"), list) else []
    first = results[0] if results and isinstance(results[0], dict) else {}
    data = first.get("data")
    if isinstance(data, list) and data:
        return dict(first)
    return None


def _parent_asset_context(parent: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(parent, dict):
        return {}
    if isinstance(parent.get("asset_context"), dict) and parent.get("asset_context"):
        return dict(parent["asset_context"])
    results = parent.get("skill_results") if isinstance(parent.get("skill_results"), list) else []
    first = results[0] if results and isinstance(results[0], dict) else {}
    intelligent = first.get("intelligent_analysis") if isinstance(first.get("intelligent_analysis"), dict) else {}
    ctx = intelligent.get("context") if isinstance(intelligent.get("context"), dict) else {}
    asset = ctx.get("asset_context") if isinstance(ctx.get("asset_context"), dict) else {}
    return dict(asset) if isinstance(asset, dict) else {}


def _visual_follow_up_values(requested_context: dict[str, Any]) -> dict[str, Any]:
    point = _dict_or_empty(requested_context.get("selected_data_point"))
    return _dict_or_empty(point.get("values"))


def _is_visual_follow_up(requested_context: dict[str, Any]) -> bool:
    if str(requested_context.get("visual_analysis_scope") or "").strip() == "page":
        return False
    if requested_context.get("chart_bound_source"):
        return True
    point = _dict_or_empty(requested_context.get("selected_data_point"))
    values = _visual_follow_up_values(requested_context)
    if values.get("chart_bound_source"):
        return True
    return str(point.get("targetType") or "") in {"chart", "table", "text"}


def _visual_analysis_scope(requested_context: dict[str, Any]) -> str:
    requested = str(requested_context.get("visual_analysis_scope") or "").strip()
    if requested in {"chart", "page"}:
        return requested
    return "chart" if _is_visual_follow_up(requested_context) else "page"


def _is_rail_brief_context(requested_context: dict[str, Any]) -> bool:
    policy = _dict_or_empty(requested_context.get("analysis_policy"))
    if str(policy.get("resultFormat") or policy.get("result_format") or "").strip() == "brief_visual":
        return True
    return str(requested_context.get("visual_analysis_scope") or "").strip() in {"chart", "page"}


def _infer_chart_fields(rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    if not rows:
        return [], []
    skip = {"_visual_source", "fieldLabels", "field_labels", "raw"}
    keys = [str(key) for key in rows[0].keys() if str(key) not in skip and not str(key).startswith("_")]
    metrics: list[str] = []
    dimensions: list[str] = []
    for key in keys:
        numeric = 0
        for row in rows:
            try:
                number = float(row.get(key))
            except (TypeError, ValueError):
                continue
            if number == number and number not in {float("inf"), float("-inf")}:
                numeric += 1
        if numeric >= max(1, (len(rows) + 1) // 2):
            metrics.append(key)
        else:
            dimensions.append(key)
    time_dims = [
        item
        for item in dimensions
        if any(token in item.lower() for token in ("month", "date", "week", "year", "day", "time", "月份", "日期"))
    ]
    dimensions = time_dims + [item for item in dimensions if item not in time_dims]
    return metrics, dimensions


def _visual_analysis_source_tables(requested_context: dict[str, Any]) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in _list_of_dicts(requested_context.get("visual_analysis_sources")):
        for table in _list_of_dicts(source.get("tables")):
            table_id = str(table.get("id") or table.get("code") or "").strip()
            if not table_id or table_id in seen:
                continue
            seen.add(table_id)
            tables.append(table)
    return tables


def _visual_source_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("rows", "visual_rows"):
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        parsed: list[dict[str, Any]] = []
        for item in rows[:200]:
            if not isinstance(item, dict):
                continue
            raw = item.get("raw") if isinstance(item.get("raw"), dict) else item
            if isinstance(raw, dict):
                parsed.append(dict(raw))
        if parsed:
            return parsed
    return []


def _embedded_visual_query_result(requested_context: dict[str, Any]) -> dict[str, Any] | None:
    rows = _visual_source_rows(_visual_follow_up_values(requested_context))
    if not rows:
        return None
    return {"data": rows, "semantic_info": {"visual_rows_reused": True, "visual_scope": "chart"}}


def _enrich_query_provenance(
    semantic: Any,
    *,
    requested_context: dict[str, Any],
    asset_context: dict[str, Any],
    parent: dict[str, Any] | None,
    result_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = dict(semantic) if isinstance(semantic, dict) else {}
    parent_results = parent.get("skill_results") if isinstance(parent, dict) and isinstance(parent.get("skill_results"), list) else []
    parent_result = parent_results[0] if parent_results and isinstance(parent_results[0], dict) else {}
    parent_semantic = parent_result.get("semantic_info") if isinstance(parent_result.get("semantic_info"), dict) else {}
    parent_evidence = parent_result.get("evidence") if isinstance(parent_result.get("evidence"), dict) else {}
    values = _visual_follow_up_values(requested_context)
    tables = (
        _list_of_dicts(asset_context.get("selected_data_tables"))
        or _list_of_dicts(requested_context.get("selected_data_tables"))
        or _list_of_dicts(values.get("selected_data_tables"))
    )
    rows = result_rows if isinstance(result_rows, list) else []
    snapshot = provenance_dataset_snapshot(
        payload.get("source_snapshot"),
        parent_semantic.get("source_snapshot"),
        parent_evidence.get("source_snapshot"),
        requested_context.get("dataset_snapshot"),
        values.get("dataset_snapshot"),
        *tables,
        schema_material=[
            payload.get("schema_mapping"),
            parent_semantic.get("schema_mapping"),
            tables,
            rows,
        ],
        content_material=rows,
    )
    versions = provenance_metric_versions(
        payload.get("metric_versions"),
        parent_semantic.get("metric_versions"),
        parent_evidence.get("metric_versions"),
        asset_context.get("metric_dictionary_definitions"),
    )
    if snapshot.get("version") or snapshot.get("schema_fingerprint") or snapshot.get("id"):
        payload["source_snapshot"] = snapshot
    if versions:
        payload["metric_versions"] = versions
    return payload


def _page_visual_query_result(
    services: Any,
    tenant_id: str,
    user_id: str,
    requested_context: dict[str, Any],
) -> dict[str, Any] | None:
    combined: list[dict[str, Any]] = []
    labels: list[str] = []
    plan: dict[str, Any] | None = None
    repository = getattr(services, "task_repository", None)
    getter = getattr(repository, "get_task", None)
    for source in _list_of_dicts(requested_context.get("visual_analysis_sources")):
        result: dict[str, Any] | None = None
        task_id = str(source.get("analysis_task_id") or "").strip()
        if task_id and callable(getter):
            task = getter(task_id)
            if task and task.get("tenant_id") == tenant_id and task.get("user_id") == user_id:
                result = _parent_visual_query_result(task)
                if plan is None and isinstance(task.get("analysis_plan"), dict):
                    plan = dict(task["analysis_plan"])
        if result is None:
            rows = _visual_source_rows(source)
            if rows:
                result = {"data": rows}
        if result is None:
            continue
        label = str(source.get("label") or source.get("id") or task_id)[:160]
        for row in result.get("data") or []:
            if isinstance(row, dict):
                combined.append({**row, "_visual_source": label})
        labels.append(label)
    if not combined:
        return None
    return {
        "data": combined,
        "semantic_info": {"page_visual_union": True, "visual_sources": labels},
        "_analysis_plan": plan,
    }


def _take_reused_visual(
    services: Any,
    tenant_id: str,
    user_id: str,
    requested_context: dict[str, Any],
    parent: dict[str, Any] | None,
    visual_scope: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if visual_scope == "page":
        page_visual = _page_visual_query_result(services, tenant_id, user_id, requested_context)
        if page_visual is None:
            return None, None
        plan = page_visual.get("_analysis_plan") if isinstance(page_visual.get("_analysis_plan"), dict) else None
        reused = {key: value for key, value in page_visual.items() if key != "_analysis_plan"}
        return reused, plan if isinstance(plan, dict) else None
    if not _is_visual_follow_up(requested_context):
        return None, None
    parent_result = _parent_visual_query_result(parent)
    if parent_result is not None:
        plan = parent.get("analysis_plan") if isinstance(parent, dict) and isinstance(parent.get("analysis_plan"), dict) else None
        return parent_result, plan
    return _embedded_visual_query_result(requested_context), None


def _reused_visual_asset_context(
    requested_context: dict[str, Any],
    parent: dict[str, Any] | None,
) -> dict[str, Any]:
    parent_asset = _parent_asset_context(parent)
    selected = _list_of_dicts(requested_context.get("selected_data_tables"))
    if not selected:
        selected = _list_of_dicts(parent_asset.get("selected_data_tables"))
    return {
        **parent_asset,
        "selected_data_tables": selected,
        "visual_rows_reused": True,
    }


def _selected_raw_tables_conflict(asset_context: dict[str, Any]) -> bool:
    selected = _list_of_dicts(asset_context.get("selected_data_tables"))
    raw_tables = [
        table
        for table in selected
        if not str(table.get("datasetId") or "").strip()
        and str(table.get("relativePath") or "").strip()
    ]
    return bool(raw_tables) and (len(raw_tables) != 1 or len(selected) != 1)


def _visual_follow_up_planning_question(requested_context: dict[str, Any], question: str) -> str:
    if _is_visual_follow_up(requested_context):
        values = _visual_follow_up_values(requested_context)
        source = str(requested_context.get("follow_up_source_question") or values.get("question") or "").strip()
        if source and source != question:
            return f"{source}\n{question}"
        return question
    labels: list[str] = []
    for source in _list_of_dicts(requested_context.get("visual_analysis_sources")):
        label = str(source.get("question") or source.get("label") or "").strip()
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= 12:
            break
    if labels:
        header = "当前页面可视化：" + "；".join(labels)
        if header != question:
            return f"{header}\n{question}"
    return question


def _inherit_chart_follow_up_context(
    requested_context: dict[str, Any],
    parent: dict[str, Any] | None,
) -> dict[str, Any]:
    """Bind every visualization follow-up to the chart's dataset and executed plan."""

    context = dict(requested_context)
    values = _visual_follow_up_values(context)
    selected = _list_of_dicts(context.get("selected_data_tables"))
    if not selected:
        selected = _list_of_dicts(values.get("selected_data_tables"))
        if not selected:
            selected = _list_of_dicts(_parent_asset_context(parent).get("selected_data_tables"))
        if selected:
            context["selected_data_tables"] = selected
    visual_follow_up = _is_visual_follow_up(context)
    if visual_follow_up:
        context["chart_bound_source"] = True
        if not str(context.get("follow_up_source_question") or "").strip():
            source_question = str(values.get("question") or "").strip()
            if source_question:
                context["follow_up_source_question"] = source_question
    raw_bound = any(
        isinstance(table, dict)
        and not str(table.get("datasetId") or "").strip()
        and str(table.get("relativePath") or table.get("id") or table.get("code") or "").strip()
        for table in selected
    )
    should_hint = not raw_bound and (visual_follow_up or not _selected_tables_have_query_semantics(selected))
    if not _dict_or_empty(context.get("analysis_plan_hint")) and should_hint:
        parent_plan = parent.get("analysis_plan") if isinstance(parent, dict) and isinstance(parent.get("analysis_plan"), dict) else {}
        dataset_id = str(parent_plan.get("dataset_id") or "").strip()
        metrics = _string_list(parent_plan.get("metrics"))
        dimensions = _string_list(parent_plan.get("dimensions"))
        ephemeral_csv = dataset_id.startswith("csv_")
        if dataset_id and metrics and dimensions and not ephemeral_csv:
            context["analysis_plan_hint"] = {
                "dataset_id": dataset_id,
                "metrics": metrics,
                "dimensions": dimensions,
                "chart_types": _string_list(parent_plan.get("chart_types")),
                "analysis_angles": _string_list(parent_plan.get("analysis_angles")),
            }
    return context


def _selected_tables_have_query_semantics(tables: list[dict[str, Any]]) -> bool:
    for table in tables:
        metric_codes = _string_list(table.get("metricCodes")) or _string_list(table.get("metric_codes"))
        dimension_codes = _string_list(table.get("dimensionCodes")) or _string_list(table.get("dimension_codes"))
        if str(table.get("datasetId") or "").strip() and metric_codes and dimension_codes:
            return True
        if not str(table.get("datasetId") or "").strip() and str(table.get("relativePath") or "").strip():
            return True
    return False


def _build_asset_context(
    services: PlatformServices,
    tenant_id: str,
    question: str,
    page_context: dict[str, Any],
    *,
    user_id: str = "",
) -> dict[str, Any]:
    store = getattr(services, "data_asset_store", None)
    if store is None:
        return {}
    try:
        bundle = store.list_published_bundle(tenant_id)
    except KeyError as exc:
        if exc.args != ("tenant_not_provisioned",):
            raise
        return {}

    selected_topic = page_context.get("selected_topic") if isinstance(page_context, dict) else None
    requested_data_tables = _list_of_dicts(page_context.get("selected_data_tables")) if isinstance(page_context, dict) else []
    requested_memory_ids = _string_list(page_context.get("analysis_memory_ids")) if isinstance(page_context, dict) else []
    # The picker and Data Management render raw tables directly from the
    # selected institution's delivered CSV folder. Resolve them from that same
    # catalog here as well: stored raw-table rows may describe an old delivery
    # and must never make a currently visible CSV look unauthorized.
    csv_source = getattr(getattr(services, "data_acquisition_service", None), "csv_source", None)
    if csv_source is not None:
        raw_tables = csv_source.for_tenant(tenant_id).table_assets()
    else:
        # Isolated callers without the acquisition service retain the store
        # contract; all running application services have a CSV source.
        raw_tables = bundle.get("raw_tables", [])
    multi_page_tables = [
        _multi_page_data_analysis_table(item)
        for item in bundle.get("page_data", [])
        if isinstance(item, dict)
        and str(item.get("institutionScope") or "") == "multi_institution"
    ]
    published_tables = [
        *raw_tables,
        *bundle.get("topic_tables", []),
        *multi_page_tables,
    ]
    metric_preset = _resolve_metric_preset_source(
        getattr(services, "metric_dictionary_store", None),
        tenant_id,
        question,
        published_tables,
    )
    selected_data_tables = []
    for requested in requested_data_tables[:8]:
        requested_ids = {
            str(requested.get("id") or "").strip(),
            str(requested.get("code") or "").strip(),
        } - {""}
        matched = next(
            (
                item
                for item in published_tables
                if requested_ids
                & {
                    str(item.get("id") or "").strip(),
                    str(item.get("code") or item.get("tableNameEn") or "").strip(),
                }
            ),
            None,
        )
        if matched is None:
            raise PermissionError("selected_data_asset_not_published_or_not_authorized")
        if str(matched.get("kind") or "") == "page_data":
            if not user_id:
                raise PermissionError("selected_multi_page_data_requires_user_context")
            from backend.platform.api.routes.assets import read_page_data_rows_payload

            resolved = read_page_data_rows_payload(
                services,
                tenant_id=tenant_id,
                user_id=user_id,
                page_data_id=str(matched.get("id") or ""),
                consumer="self_analysis",
            )
            matched = {
                **matched,
                "previewRows": resolved.get("rows", []),
                "fieldLabels": resolved.get("field_labels", {}),
                "sourceSnapshot": {
                    "page_data_id": str(matched.get("id") or ""),
                    "relationship_group_id": str(resolved.get("relationship_group_id") or ""),
                    "schema_fingerprint": str(resolved.get("schema_fingerprint") or ""),
                    "institution_scope": str(resolved.get("institution_scope") or ""),
                },
            }
        selected_data_tables.append(matched)
    if not selected_data_tables and isinstance(metric_preset.get("selected_table"), dict):
        # Only a published dictionary metric with an explicit table mapping may
        # supply this preset. Never choose the first available tenant table.
        selected_data_tables.append(metric_preset["selected_table"])
    published_memories = [
        *bundle.get("intents", []),
        *bundle.get("analysis_experiences", []),
        *bundle.get("behavior_habits", []),
    ]
    memory_by_id = {
        str(item.get("id") or ""): item
        for item in published_memories
        if isinstance(item, dict) and item.get("id")
    }
    selected_memories = []
    for memory_id in requested_memory_ids[:12]:
        matched_memory = memory_by_id.get(memory_id)
        if matched_memory is None:
            raise PermissionError("selected_analysis_memory_not_published_or_not_authorized")
        selected_memories.append(_bounded_extension_asset(matched_memory))
    normalized_question = question.lower()
    matched_intents = []
    for intent in bundle.get("intents", []):
        keywords = [
            keyword.strip().lower()
            for keyword in str(intent.get("keywords") or "").replace("，", ",").split(",")
            if keyword.strip()
        ]
        if any(keyword and keyword in normalized_question for keyword in keywords):
            matched_intents.append(intent)

    topic_codes = {
        str(intent.get("relatedTopic") or "")
        for intent in matched_intents
        if intent.get("relatedTopic")
    }
    if isinstance(selected_topic, dict) and selected_topic.get("code"):
        topic_codes.add(str(selected_topic["code"]))

    topics = [
        topic
        for topic in bundle.get("topic_tables", [])
        if str(topic.get("code") or "") in topic_codes or str(topic.get("id") or "") in topic_codes
    ]
    experience_ids = {
        str(topic.get("relatedExperience") or "")
        for topic in topics
        if topic.get("relatedExperience")
    }
    experience_ids.update(
        str(intent.get("relatedExperience") or "")
        for intent in matched_intents
        if intent.get("relatedExperience")
    )
    experiences = [
        experience
        for experience in bundle.get("analysis_experiences", [])
        if str(experience.get("id") or "") in experience_ids
    ]
    metric_dictionary_definitions = _metric_dictionary_context(
        services,
        tenant_id,
        question,
        selected_data_tables,
    )
    related_detail_tables = _related_detail_tables(
        services,
        tenant_id,
        selected_data_tables,
        published_tables,
    )
    return {
        "matched_intents": matched_intents[:3],
        "topics": topics[:3],
        "selected_data_tables": selected_data_tables[:8],
        "related_detail_tables": related_detail_tables[:4],
        "detail_table_status": "available" if related_detail_tables else "unavailable",
        "detail_table_message": "" if related_detail_tables else "没有更细粒度数据，请关联明细数据",
        "analysis_memories": selected_memories,
        "experiences": experiences[:3],
        "metric_dictionary_definitions": metric_dictionary_definitions,
        "metric_preset": {key: value for key, value in metric_preset.items() if key != "selected_table"},
        "raw_table_count": len(raw_tables),
        "multi_institution_page_data_count": len(multi_page_tables),
        "knowledge_file_count": len(bundle.get("knowledge_files", [])),
    }


def _multi_page_data_analysis_table(item: dict[str, Any]) -> dict[str, Any]:
    """Expose bounded page-data metadata without exposing cross-tenant raw tables."""

    page_data_id = str(item.get("id") or "")
    code = f"page_data_{page_data_id}"
    return {
        "id": page_data_id,
        "kind": "page_data",
        "name": str(item.get("name") or item.get("sourceTableName") or "多机构页面数据"),
        "tableNameCn": str(item.get("name") or item.get("sourceTableName") or "多机构页面数据"),
        "tableNameEn": code,
        "code": code,
        "description": "由跨机构表关系生成并经过权限、关系和版本校验的多机构页面数据。",
        "relativePath": f"page-data://{page_data_id}",
        "sourceKey": str(item.get("sourceKey") or ""),
        "relationshipGroupId": str(item.get("relationshipGroupId") or ""),
        "schemaFingerprint": str(item.get("schemaFingerprint") or ""),
        "institutionScope": "multi_institution",
        "fields": [dict(field) for field in item.get("sourceFields", []) if isinstance(field, dict)],
        "metricCodes": [str(field) for field in item.get("metricFields", []) if str(field)],
        "defaultMetrics": [str(field) for field in item.get("metricFields", []) if str(field)],
        "dimensionCodes": [str(field) for field in item.get("dimensionFields", []) if str(field)],
        "defaultDimensions": [str(field) for field in item.get("dimensionFields", []) if str(field)],
        "chartTypes": ["table", "column", "line", "bar", "pie"],
    }


def _related_detail_tables(
    services: PlatformServices,
    tenant_id: str,
    selected_tables: list[dict[str, Any]],
    published_tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve only explicitly linked, currently published finer-grain tables."""

    if not selected_tables:
        return []
    lineage_store = getattr(services, "lineage_store", None)
    if lineage_store is None:
        return []
    table_by_alias: dict[str, dict[str, Any]] = {}
    for table in published_tables:
        for alias in _table_aliases(table):
            table_by_alias.setdefault(alias, table)
    selected_aliases = {alias for table in selected_tables for alias in _table_aliases(table)}
    related: list[dict[str, Any]] = []
    seen: set[str] = set()
    for edge in lineage_store.list_edges(tenant_id):
        source_id = str(edge.get("source_id") or "").strip()
        target_id = str(edge.get("target_id") or "").strip()
        other_id = target_id if source_id in selected_aliases else source_id if target_id in selected_aliases else ""
        candidate = table_by_alias.get(other_id)
        candidate_id = str((candidate or {}).get("id") or "")
        if not candidate or not candidate_id or candidate_id in seen or _table_aliases(candidate) & selected_aliases:
            continue
        seen.add(candidate_id)
        related.append(candidate)
    return sorted(
        related,
        key=lambda item: (0 if item.get("tableNameEn") or item.get("relativePath") else 1, str(item.get("name") or item.get("tableNameCn") or "")),
    )


def _table_aliases(table: dict[str, Any]) -> set[str]:
    return {
        str(table.get(key) or "").strip()
        for key in ("id", "code", "datasetId", "tableNameEn", "sourceKey")
        if str(table.get(key) or "").strip()
    }


def _requires_selected_production_source(
    services: PlatformServices,
    page_context: dict[str, Any],
    asset_context: dict[str, Any],
) -> bool:
    """Never revive mock metric defaults while production semantic data is absent."""

    has_selected_source = bool(
        _list_of_dicts(asset_context.get("selected_data_tables"))
        or _list_of_dicts(asset_context.get("topics"))
    )
    return (
        not has_selected_source
        and str(page_context.get("route") or "").strip() == "self-analysis/query"
        and str(getattr(services, "data_source_mode", "")).strip() == "production_data_source_not_configured"
    )


def _selected_table_requires_semantic_registration(asset_context: dict[str, Any]) -> bool:
    """Block only tables that have neither governed nor bounded raw semantics."""
    selected_tables = _list_of_dicts(asset_context.get("selected_data_tables"))
    return any(
        not str(table.get("datasetId") or "").strip()
        and not (
            str(table.get("id") or "").strip()
            and str(table.get("relativePath") or "").strip()
            and isinstance(table.get("fields"), list)
            and bool(table.get("fields"))
        )
        for table in selected_tables
    )


def _resolve_metric_preset_source(
    store: Any,
    tenant_id: str,
    question: str,
    published_tables: list[dict[str, Any]],
) -> dict[str, Any]:
    """Resolve a dictionary metric only when it names an authorized table."""
    if store is None:
        return {"status": "unavailable", "metrics": []}
    try:
        metrics = store.list(tenant_id)
    except Exception:
        return {"status": "unavailable", "metrics": []}

    candidates = [
        metric
        for metric in metrics
        if isinstance(metric, dict) and _metric_dictionary_item_matches_question(metric, question)
    ][:8]
    summary = [
        {
            "metric_id": str(metric.get("metricId") or ""),
            "metric_name": str(metric.get("metricName") or ""),
            "dataset_id": str(metric.get("datasetId") or ""),
        }
        for metric in candidates
    ]
    for metric in candidates:
        metric_code = str(metric.get("metricCode") or "").strip()
        dataset_id = str(metric.get("datasetId") or "").strip()
        if (
            str(metric.get("semanticStatus") or "").strip().lower() != "published"
            or not metric_code
            or not dataset_id
        ):
            continue
        selected = next(
            (
                table
                for table in published_tables
                if _table_supports_dictionary_metric(table, dataset_id, metric_code)
            ),
            None,
        )
        if selected is not None:
            return {
                "status": "resolved",
                "metrics": [summary_item for summary_item in summary if summary_item["metric_id"] == str(metric.get("metricId") or "")],
                "selected_table": selected,
            }
    return {"status": "no_executable_mapping" if candidates else "no_match", "metrics": summary}


def _metric_dictionary_item_matches_question(metric: dict[str, Any], question: str) -> bool:
    normalized_question = str(question or "").casefold()
    name = str(metric.get("metricName") or "").strip().casefold()
    code = str(metric.get("metricCode") or "").strip().casefold()
    short_name = name.split("（", 1)[0].split("(", 1)[0].strip()
    aliases = ("放款",) if code == "loan_amount" else ()
    return any(token and len(token) >= 2 and token in normalized_question for token in (name, short_name, code, *aliases))


def _table_supports_dictionary_metric(table: dict[str, Any], dataset_id: str, metric_code: str) -> bool:
    table_identifiers = {
        str(table.get("datasetId") or "").strip(),
        str(table.get("code") or table.get("tableNameEn") or "").strip(),
        str(table.get("id") or "").strip(),
    } - {""}
    metric_codes = set(_string_list(table.get("metricCodes")))
    return dataset_id in table_identifiers or metric_code in metric_codes


def _metric_dictionary_context(
    services: PlatformServices,
    tenant_id: str,
    question: str,
    selected_tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    store = getattr(services, "metric_dictionary_store", None)
    if store is None:
        return []
    try:
        metrics = store.list(tenant_id)
    except Exception:
        return []
    if not metrics:
        from backend.platform.metrics.defaults import load_default_metric_dictionary

        metrics = load_default_metric_dictionary()
    selected_codes = {
        code
        for table in selected_tables
        for code in _string_list(table.get("metricCodes"))
        if isinstance(table, dict)
    }
    normalized_question = question.casefold()
    result: list[dict[str, Any]] = []
    resolved_codes: set[tuple[str, str]] = set()
    resolved_names: set[str] = set()
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        name = str(metric.get("metricName") or "").strip()
        code = str(metric.get("metricCode") or "").strip()
        short_name = name.split("（", 1)[0].split("(", 1)[0].strip()
        matched = any(
            token and token.casefold() in normalized_question
            for token in (name, short_name, code)
        ) or bool(code and code in selected_codes)
        if not matched:
            continue
        result.append({
            key: metric.get(key)
            for key in (
                "metricId", "metricName", "definition", "valueLogic", "sourceTable", "dimension",
                "description", "applicationScene", "systemSource", "statTime", "referenceDocument",
                "metricCode", "datasetId", "aggregationType", "numeratorField", "denominatorField",
                "multiplier", "unit", "grain", "semanticStatus", "semanticVersion",
            )
            if metric.get(key) not in (None, "")
        })
        resolved_codes.add((str(metric.get("datasetId") or ""), code))
        resolved_names.add(name.casefold())
        if len(result) >= 20:
            break
    # A selected table can reference executable metrics that are not yet
    # documented in the tenant's descriptive dictionary. Bind the reviewed
    # semantic catalog as a fail-closed fallback so the model still receives
    # the table-to-metric formula instead of guessing it.
    semantic_catalog = getattr(getattr(services, "workflow", None), "metric_semantic_catalog", None)
    if semantic_catalog is not None:
        for table in selected_tables:
            dataset_id = str(table.get("datasetId") or "").strip()
            metric_codes = tuple(_string_list(table.get("metricCodes")))
            if not dataset_id or not metric_codes:
                continue
            try:
                definitions = semantic_catalog.resolve(tenant_id, dataset_id, metric_codes)
            except Exception:
                continue
            relevant_definitions = [
                definition
                for definition in definitions
                if _metric_definition_matches_question(definition, normalized_question)
            ]
            # If the question names no metric at all, still provide a bounded
            # table-level semantic overview. Otherwise only fill the gaps for
            # metrics actually discussed in this question.
            if not relevant_definitions and not result:
                relevant_definitions = definitions[:8]
            for definition in relevant_definitions:
                code = str(definition.get("metric_code") or "").strip()
                metric_name = str(definition.get("metric_name") or code).strip()
                if not code or (dataset_id, code) in resolved_codes or metric_name.casefold() in resolved_names:
                    continue
                aggregation = str(definition.get("aggregation") or "").strip()
                numerator = str(definition.get("numerator") or "").strip()
                denominator = str(definition.get("denominator") or "").strip()
                formula = (
                    f"{numerator} / {denominator}"
                    if aggregation == "ratio" and numerator and denominator
                    else f"{aggregation}({code})"
                )
                result.append({
                    "metricId": definition.get("metric_id") or "",
                    "metricName": definition.get("metric_name") or code,
                    "definition": f"{definition.get('metric_name') or code}，按{definition.get('grain') or '数据表粒度'}统计。",
                    "valueLogic": formula,
                    "metricCode": code,
                    "datasetId": dataset_id,
                    "aggregationType": aggregation,
                    "numeratorField": numerator,
                    "denominatorField": denominator,
                    "multiplier": definition.get("multiplier", 1),
                    "unit": definition.get("unit") or "",
                    "grain": definition.get("grain") or "",
                    "semanticStatus": "published",
                    "semanticVersion": definition.get("version") or "",
                    "definitionSource": definition.get("source") or "system_catalog",
                })
                resolved_codes.add((dataset_id, code))
                resolved_names.add(metric_name.casefold())
                if len(result) >= 20:
                    return result
    return result


def _metric_definition_matches_question(definition: dict[str, Any], normalized_question: str) -> bool:
    code = str(definition.get("metric_code") or "").strip().casefold()
    name = str(definition.get("metric_name") or "").strip().casefold()
    short_name = name.split("（", 1)[0].split("(", 1)[0].strip()
    aliases = {code, name, short_name}
    if code == "loan_amount":
        aliases.add("放款")
    return any(alias and alias in normalized_question for alias in aliases)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None


def _resolve_selected_model(
    services: PlatformServices,
    tenant_id: str,
    page_context: dict[str, Any],
    user_id: str = "",
) -> dict[str, Any] | None:
    application_module = str(page_context.get("model_application_module") or "").strip()
    if application_module:
        selected = select_model_for_application(
            services.system_config_store,
            tenant_id,
            application_module,
            _dict_or_none(page_context.get("model_application_selection")),
            user_id=user_id,
            reveal_secret=True,
        )
        if selected is None:
            return require_model_for_application(
                services.system_config_store,
                tenant_id,
                application_module,
                user_id=user_id,
                reveal_secret=True,
            )
        return selected
    selected_model = _dict_or_none(page_context.get("selected_model"))
    if not selected_model:
        return None
    raw_model_id = str(selected_model.get("id") or "").strip()
    legacy_model_id, separator, legacy_submodel = raw_model_id.partition("::")
    model_id = str(selected_model.get("integrationId") or legacy_model_id).strip()
    if not model_id:
        raise ValueError("selected_model_id_required")
    getter = getattr(services.system_config_store, "get_model", None)
    if not callable(getter):
        raise RuntimeError("model_registry_unavailable")
    stored_model = getter(tenant_id, model_id, reveal_secret=True)
    if stored_model is None and user_id:
        list_owned = getattr(services.system_config_store, "list_models_owned_by", None)
        if callable(list_owned):
            stored_model = next(
                (
                    item
                    for item in list_owned(user_id, tenant_id, reveal_secret=True)
                    if str(item.get("id") or "") == model_id
                ),
                None,
            )
    if isinstance(stored_model, dict):
        if str(stored_model.get("status") or "") not in {"available", "connected"}:
            raise RuntimeError("selected_model_not_available")
        requested_submodel = str(
            selected_model.get("selectedModelName")
            or selected_model.get("selected_model_name")
            or (legacy_submodel if separator else "")
            or next(iter(selected_model.get("enabledModels") or []), "")
        ).strip()
        if not requested_submodel:
            return stored_model
        allowed_submodels = {
            str(item).strip()
            for item in [*(stored_model.get("enabledModels") or []), *(stored_model.get("availableModels") or [])]
            if str(item).strip()
        }
        if requested_submodel not in allowed_submodels:
            raise PermissionError("selected_submodel_not_registered_for_model")
        return {
            **stored_model,
            "enabledModels": [requested_submodel],
            "availableModels": [requested_submodel],
            "selectedModelName": requested_submodel,
            "strictModelSelection": True,
        }
    raise PermissionError("selected_model_not_registered_for_tenant")


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _analysis_cache_context(
    services: PlatformServices,
    *,
    user_id: str,
    tenant_id: str,
    question: str,
    requested_context: dict[str, Any],
    asset_context: dict[str, Any],
    selected_model: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Build a complete cache identity or disable caching when any input is ambiguous."""
    code_version = str(
        os.getenv("SMART_DATA_AGENT_CODE_VERSION")
        or os.getenv("GIT_COMMIT_SHA")
        or ""
    ).strip()
    selected_tables = _list_of_dicts(asset_context.get("selected_data_tables"))
    if not code_version or not selected_tables:
        return None

    csv_tables: list[dict[str, Any]] = []
    for table in selected_tables:
        content_hash = str(table.get("contentHash") or "").strip().lower()
        schema_fingerprint = str(table.get("schemaFingerprint") or "").strip().lower()
        relative_path = str(table.get("relativePath") or "").strip()
        if len(content_hash) != 64 or not schema_fingerprint or not relative_path:
            return None
        csv_tables.append({
            "table_id": str(table.get("id") or table.get("code") or "").strip(),
            "source_key": str(table.get("sourceKey") or "").strip(),
            "relative_path": relative_path,
            "content_hash": content_hash,
            "schema_fingerprint": schema_fingerprint,
            "schema_version": str(table.get("schemaVersion") or schema_fingerprint).strip(),
            "asset_version": str(table.get("assetVersion") or table.get("version") or "").strip(),
        })
    csv_tables.sort(key=lambda item: (item["table_id"], item["relative_path"]))
    csv_snapshot = {"tables": csv_tables}

    authorization_snapshot = _analysis_authorization_snapshot(
        services,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    if authorization_snapshot is None:
        return None

    semantic_versions = _analysis_semantic_versions(asset_context, csv_tables)
    skill_versions = sorted(
        [
            {
                "skill_id": str(item.get("id") or "").strip(),
                "version": str(item.get("version") or item.get("assetVersion") or "pinned").strip(),
            }
            for item in _list_of_dicts(requested_context.get("analysis_context_skills"))
            if str(item.get("id") or "").strip()
        ],
        key=lambda item: (item["skill_id"], item["version"]),
    )
    model = _dict_or_empty(selected_model)
    model_version = "::".join(
        part
        for part in (
            str(model.get("id") or model.get("integrationId") or "server-default").strip(),
            str(model.get("selectedModelName") or model.get("model") or "").strip(),
            str(model.get("version") or model.get("updatedAt") or "").strip(),
        )
        if part
    )
    institutions = sorted({tenant_id, *_analysis_institution_ids(requested_context)})
    filters = {
        "filters": _dict_or_empty(requested_context.get("filters")),
        "selected_data_point": _dict_or_empty(requested_context.get("selected_data_point")),
        "analysis_trigger": str(requested_context.get("analysis_trigger") or "manual"),
    }
    analysis_policy = _dict_or_empty(requested_context.get("analysis_policy"))
    time_grain = str(
        requested_context.get("time_grain")
        or requested_context.get("timeGrain")
        or analysis_policy.get("timeGrain")
        or analysis_policy.get("time_grain")
        or ""
    ).strip()
    cache_key = safe_cache_key(
        tenant_id=tenant_id,
        question=question,
        authorization_snapshot=authorization_snapshot,
        institution_ids=institutions,
        csv_snapshot=csv_snapshot,
        semantic_versions=semantic_versions,
        filters=filters,
        time_grain=time_grain,
        skill_versions=skill_versions,
        model_version=model_version,
        code_version=code_version,
    )
    return {
        "cache_key": cache_key,
        "authorization_hash": _stable_json_hash(authorization_snapshot),
        "csv_snapshot_hash": _stable_json_hash(csv_snapshot),
        "semantic_version_hash": _stable_json_hash(semantic_versions),
        "execution_version_hash": _stable_json_hash({
            "skills": skill_versions,
            "model": model_version,
            "code": code_version,
        }),
        "expected_csv_tables": csv_tables,
    }


def _analysis_authorization_snapshot(
    services: PlatformServices,
    *,
    tenant_id: str,
    user_id: str,
) -> dict[str, Any] | None:
    repository = getattr(getattr(services.permission_broker, "enforcer", None), "repository", None)
    if repository is None:
        return None
    try:
        assignments = repository.get_user_roles(user_id, tenant_id)
        roles = []
        for assignment in sorted(assignments, key=lambda item: item.role_id):
            policies = sorted(
                (asdict(policy) for policy in repository.get_role_policies(assignment.role_id)),
                key=lambda item: (
                    int(item.get("priority") or 0),
                    str(item.get("tenant_id") or ""),
                    str(item.get("obj") or ""),
                    str(item.get("act") or ""),
                    str(item.get("effect") or ""),
                ),
            )
            roles.append({
                "role_id": assignment.role_id,
                "assignment_tenant_id": assignment.tenant_id,
                "policies": policies,
            })
    except Exception:
        return None
    if not roles:
        return None
    return {"tenant_id": tenant_id, "user_id": user_id, "roles": roles}


def _analysis_semantic_versions(
    asset_context: dict[str, Any],
    csv_tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result = [
        {
            "metric_id": str(item.get("metricId") or item.get("metricCode") or "").strip(),
            "dataset_id": str(item.get("datasetId") or "").strip(),
            "version": str(
                item.get("semanticVersion")
                or item.get("definitionSource")
                or "published-unversioned"
            ).strip(),
            "status": str(item.get("semanticStatus") or "published").strip(),
        }
        for item in _list_of_dicts(asset_context.get("metric_dictionary_definitions"))
        if str(item.get("metricId") or item.get("metricCode") or "").strip()
    ]
    if not result:
        result = [
            {
                "metric_id": "",
                "dataset_id": item["table_id"],
                "version": item["schema_version"],
                "status": "temporary-schema-bound",
            }
            for item in csv_tables
        ]
    return sorted(result, key=lambda item: (item["dataset_id"], item["metric_id"], item["version"]))


def _analysis_institution_ids(requested_context: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in ("institution_id", "institutionId", "selected_institution", "selectedInstitution"):
        value = requested_context.get(key)
        if isinstance(value, dict):
            value = value.get("id") or value.get("institutionId") or value.get("code")
        if str(value or "").strip():
            values.add(str(value).strip())
    for key in ("institution_ids", "institutionIds", "selected_institutions", "selectedInstitutions"):
        for value in requested_context.get(key) if isinstance(requested_context.get(key), list) else []:
            if isinstance(value, dict):
                value = value.get("id") or value.get("institutionId") or value.get("code")
            if str(value or "").strip():
                values.add(str(value).strip())
    return values


def _cache_snapshot_matches(cache_context: dict[str, Any], task: Any) -> bool:
    if str(getattr(task, "status", "")) != "completed":
        return False
    results = getattr(task, "skill_results", None)
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        return False
    first_result = results[0]
    semantic = _dict_or_empty(first_result.get("semantic_info"))
    evidence = _dict_or_empty(first_result.get("evidence"))
    snapshot = _dict_or_empty(semantic.get("source_snapshot")) or _dict_or_empty(evidence.get("source_snapshot"))
    content_hash = str(snapshot.get("content_hash") or "").strip().lower()
    schema_fingerprint = str(snapshot.get("schema_fingerprint") or "").strip().lower()
    expected = _list_of_dicts(cache_context.get("expected_csv_tables"))
    return bool(content_hash and schema_fingerprint) and any(
        content_hash == str(item.get("content_hash") or "").lower()
        and schema_fingerprint == str(item.get("schema_fingerprint") or "").lower()
        for item in expected
    )


def _stable_json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_workspace_binding(
    services: PlatformServices,
    *,
    tenant_id: str,
    user_id: str,
    requested_context: dict[str, Any],
) -> dict[str, str] | None:
    workspace_id = str(requested_context.get("workspace_id") or requested_context.get("workspaceId") or "").strip()
    thread_id = str(requested_context.get("thread_id") or requested_context.get("threadId") or "").strip()
    if not workspace_id and not thread_id:
        return None
    if not workspace_id or not thread_id:
        raise ValueError("analysis_workspace_binding_incomplete")
    services.analysis_workspace_service.workspace(tenant_id, user_id, workspace_id)
    threads = services.analysis_workspace_service.threads(tenant_id, user_id, workspace_id)
    thread = next((item for item in threads if str(item.get("thread_id") or "") == thread_id), None)
    if thread is None:
        raise PermissionError("analysis_thread_not_owned")
    if str(thread.get("status") or "") != "active":
        raise ValueError("analysis_thread_not_active")
    return {"workspace_id": workspace_id, "thread_id": thread_id}


def _append_workspace_analysis_turn(
    services: PlatformServices,
    *,
    tenant_id: str,
    user_id: str,
    question: str,
    binding: dict[str, str] | None,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if binding is None:
        return None
    intelligent = _dict_or_empty(payload.get("intelligent_analysis"))
    summary = _dict_or_empty(intelligent.get("analysis_summary"))
    answer = str(summary.get("text") or intelligent.get("analysis_summary") or "").strip()
    if not answer:
        answer = "\n".join(str(item).strip() for item in payload.get("conclusions") or [] if str(item).strip())
    results = _list_of_dicts(payload.get("skill_results"))
    artifact_refs = []
    for result in results:
        spec = result.get("visualization_spec") if isinstance(result.get("visualization_spec"), dict) else {}
        rows = result.get("data") if isinstance(result.get("data"), list) else []
        semantic = result.get("semantic_info") if isinstance(result.get("semantic_info"), dict) else {}
        field_labels = semantic.get("field_labels") if isinstance(semantic.get("field_labels"), dict) else {}
        artifact_refs.append(
            {
                "type": "follow_up_visual" if spec or rows else ("visualization" if isinstance(result.get("visualization_artifact"), dict) else "analysis_result"),
                "task_id": str(payload.get("task_id") or ""),
                "execution_id": str(payload.get("execution_id") or payload.get("task_id") or ""),
                "visualization_spec": spec,
                "rows": [row for row in rows[:24] if isinstance(row, dict)],
                "field_labels": field_labels,
            }
        )
    evidence_refs = [
        dict(result["evidence"])
        for result in results
        if isinstance(result.get("evidence"), dict)
    ]
    return services.analysis_workspace_service.append_turn(
        tenant_id,
        user_id,
        binding["thread_id"],
        {
            "question": question,
            "answer": answer or "本轮已生成数据产物，暂无文字结论。",
            "status": "completed" if str(payload.get("status") or "") == "completed" else "partial",
            "intent": _dict_or_empty(payload.get("analysis_plan")),
            "execution_plan": {
                "task_id": str(payload.get("task_id") or ""),
                "execution_id": str(payload.get("execution_id") or payload.get("task_id") or ""),
                "plan": payload.get("plan") if isinstance(payload.get("plan"), list) else [],
                "cache_hit": bool(payload.get("cache_hit")),
            },
            "artifact_refs": artifact_refs,
            "evidence_refs": evidence_refs,
        },
    )
