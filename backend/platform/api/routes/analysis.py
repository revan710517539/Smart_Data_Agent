from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from http import HTTPStatus
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import uuid4

from backend.platform.bootstrap import PlatformServices
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
        elif (
            int(automation_task.get("timeout_seconds") or 0) != analysis_deadline
            or int(automation_task.get("max_concurrency") or 0) != analysis_concurrency
            or dict(automation_task.get("retry_policy") or {}) != ANALYSIS_AUTOMATION_RETRY_POLICY
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

    parent: dict[str, Any] | None = None
    parent_task_id = str(requested_context.get("parent_task_id") or "").strip()
    if parent_task_id:
        parent = services.task_repository.get_task(parent_task_id)
        if not parent or parent.get("tenant_id") != tenant_id or parent.get("user_id") != user_id:
            raise PermissionError("Parent analysis execution is unavailable.")
        requested_context["parent_execution_id"] = str(parent.get("execution_id") or parent.get("task_id") or "")
        requested_context["revision"] = int(parent.get("revision") or 1) + 1

    trace_id = services.trace_recorder.start_trace()
    started_at = perf_counter()
    context = ExecutionContext(
        user_id=user_id,
        tenant_id=tenant_id,
        page_context={
            "trace_id": trace_id,
            **requested_context,
            "asset_context": _build_asset_context(services, tenant_id, question, requested_context),
        },
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

        if selected_model and not use_skill_solution_plan and not data_first_mode:
            progress("model_planning", 20, "running", "生成分析方案", "正在将问题转换为指标、维度、查询和可视化方案。")
        else:
            planning_source = "服务端快速语义方案" if data_first_mode else "治理后的 Skill 与服务端语义方案"
            progress("model_planning", 20, "skipped", "生成分析方案", f"已使用{planning_source}，先查询数据并减少一次模型等待。")
            progress("data_query", 30, "running", "查询业务数据", "正在执行受权限控制的语义查询并获取明细数据。")
        task = services.workflow.run(
            context,
            question,
            task=task,
            planning_hook=selected_model_planning_hook if selected_model and not use_skill_solution_plan and not data_first_mode else None,
        )
        _raise_if_cancelled(cancellation_check)
        task.trace_id = services.trace_recorder.trace_id
        query_result = dict(task.skill_results[0]) if task.skill_results else {}
        if query_result:
            query_result["evidence"] = _build_execution_evidence(query_result)
            task.skill_results[0] = query_result
        task.trace_id = services.trace_recorder.trace_id
        services.task_repository.save_task(task)
        row_count = len(query_result.get("data") or []) if isinstance(query_result, dict) else 0
        progress(
            "data_query",
            30,
            "succeeded",
            "查询业务数据",
            f"已返回 {row_count} 行结果，可先查看数据与可视化；模型将继续生成结论。",
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
        progress("model_conclusion", 50, "running", "生成分析结论", "正在基于已执行的数据证据归纳发现、原因边界与建议。")
        intelligent_analysis = intelligent_engine.analyze(
            final_request,
            planning_result,
        )
        progress(
            "model_conclusion",
            50,
            "succeeded",
            "生成分析结论",
            "已生成基于实际查询证据的分析摘要与关键发现。",
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
        services.lineage_store.record_analysis(payload)
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
    for reference in requested[:12]:
        skill_id = str(reference.get("id") or "").strip()
        if not skill_id or skill_id in seen:
            continue
        configured = skill_by_id.get(skill_id) or skill_by_id.get(legacy_skill_ids.get(skill_id, ""))
        if configured is None:
            if str(reference.get("category") or "") != "模式":
                continue
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


def _build_asset_context(
    services: PlatformServices,
    tenant_id: str,
    question: str,
    page_context: dict[str, Any],
) -> dict[str, Any]:
    store = getattr(services, "data_asset_store", None)
    if store is None:
        return {}
    try:
        bundle = store.list_published_bundle(tenant_id)
    except Exception:
        return {}

    selected_topic = page_context.get("selected_topic") if isinstance(page_context, dict) else None
    requested_data_tables = _list_of_dicts(page_context.get("selected_data_tables")) if isinstance(page_context, dict) else []
    requested_memory_ids = _string_list(page_context.get("analysis_memory_ids")) if isinstance(page_context, dict) else []
    published_tables = [
        *bundle.get("raw_tables", []),
        *bundle.get("topic_tables", []),
    ]
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
        selected_data_tables.append(matched)
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
    return {
        "matched_intents": matched_intents[:3],
        "topics": topics[:3],
        "selected_data_tables": selected_data_tables[:8],
        "analysis_memories": selected_memories,
        "experiences": experiences[:3],
        "metric_dictionary_definitions": metric_dictionary_definitions,
        "raw_table_count": len(bundle.get("raw_tables", [])),
        "knowledge_file_count": len(bundle.get("knowledge_files", [])),
    }


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
