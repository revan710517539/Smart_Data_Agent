from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
from urllib.parse import parse_qs

from backend.authz import normalize_tenant_id
from backend.authz.seed import OPERATING_TENANTS
from backend.platform.api.support import first_query_value, send_route_exception
from backend.platform.memory import MemoryRecord
from backend.platform.reports.weekly_learning import WeeklyReportLearningEngine
from backend.platform.tenancy import ExecutionContext


SAVED_REPORT_VISUAL_TYPES = frozenset({
    "kpi", "line", "area", "column", "bar", "stacked_bar", "combo", "donut",
    "scatter", "funnel", "treemap", "radar", "table", "pivot",
})
SAVED_REPORT_VISUAL_TYPE_ALIASES = {"stackedBar": "stacked_bar", "pie": "donut"}


def _institution_label(tenant_id: str) -> str:
    return str(tenant_id or "").split(":", 1)[-1].strip()


def _institution_tenant_id(institution: str, fallback_tenant_id: str) -> str:
    """Resolve a recognised display label without accepting an arbitrary scope."""
    label = str(institution or "").strip()
    return normalize_tenant_id(label) if label in OPERATING_TENANTS else fallback_tenant_id


def handle_report_analysis_results_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_report_permission(context, "read")
        handler.services.report_retention_service.enforce(context.tenant_id)
        results = handler.services.report_store.list_analysis_results(context.tenant_id, actor_user_id=context.user_id)
        results = [_hydrate_saved_analysis(handler, context.user_id, context.tenant_id, result) for result in results]
        handler._send_json({"tenant_id": context.tenant_id, "results": results, "count": len(results)})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_report_analysis_result_upsert(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ValueError("result must be an object.")
        handler._require_report_permission(context, "create")
        handler.services.report_retention_service.enforce(context.tenant_id)
        task_id = str(result.get("analysisTaskId") or result.get("analysis_task_id") or "").strip()
        result_id = str(result.get("id") or "").strip()
        try:
            task = handler.services.task_repository.get_task(task_id) if task_id else None
        except KeyError:
            task = None
        existing = handler.services.report_store.get_analysis_result(
            context.tenant_id,
            result_id,
            actor_user_id=context.user_id,
        ) if result_id else None
        # A report title is report metadata, not a new analysis execution.
        # Historical saved reports predate analysisTaskId/Topic_Data and must
        # remain editable by their owner. In that path preserve every field
        # except title and presentation preference, so metadata changes cannot
        # rewrite report evidence or source data.
        is_owned_existing_report = bool(existing)
        is_title_update = bool(existing and task_id and str(existing.get("analysisTaskId") or "") == task_id)
        if is_owned_existing_report and not task:
            requested_title = str(result.get("title") or "").strip()
            if not requested_title:
                raise ValueError("report_title_required")
            candidate_reference = result.get("topicData") if isinstance(result.get("topicData"), dict) else {}
            expected_report_id = str(existing.get("id") or "")
            is_own_report_reference = (
                candidate_reference.get("reference_type") == "report"
                and str(candidate_reference.get("reference_id") or "") == expected_report_id
            )
            # The browser can only retain a reference that was just hydrated
            # by this server for this exact report. It cannot point one user's
            # report at another report or submit arbitrary source rows.
            result = {
                **existing,
                "title": requested_title,
                "visualTypes": _saved_report_visual_types(result.get("visualTypes"), existing.get("visualTypes")),
                "visualizations": (
                    result.get("visualizations")
                    if isinstance(result.get("visualizations"), list)
                    else existing.get("visualizations")
                ),
                **({"topicData": candidate_reference} if is_own_report_reference else {}),
            }
        elif not is_title_update and (not task or task.get("tenant_id") != context.tenant_id or task.get("user_id") != context.user_id):
            raise PermissionError("saved analysis must reference an owned execution")
        result = {
            **result,
            "analysisTaskId": task_id,
            "ownerUserId": context.user_id,
            "visibility": str(result.get("visibility") or "private"),
            # Tenant ownership is server-authoritative.  A browser may supply
            # a detected upload institution for context, but it may not change
            # the tenant that owns this execution or report.
            "currentInstitution": _institution_label(context.tenant_id),
            "analysisInstitution": (
                str(result.get("analysisInstitution") or "").strip()
                if isinstance(result.get("analysisInstitution"), str)
                else ""
            ) or _institution_label(task.get("tenant_id") if task else context.tenant_id),
        }
        saved = handler.services.report_store.upsert_analysis_result(
            context.tenant_id,
            result,
            updated_by=context.user_id,
        )
        if task:
            topic_data = handler.services.topic_data_store.record_analysis_execution(
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                task=task,
                source_reference={"type": "report", "id": str(saved.get("id") or "")},
            )
            saved = {**saved, "topicData": topic_data.get("history")}
            handler.services.lineage_store.record_edge(
                context.tenant_id,
                {
                    "source_type": "analysis_task",
                    "source_id": task_id,
                    "target_type": "saved_analysis_result",
                    "target_id": str(saved.get("id") or saved.get("resultId") or ""),
                    "edge_type": "publishes",
                    "metadata": {"visibility": saved.get("visibility")},
                },
                context.user_id,
            )
        handler._send_json({"tenant_id": context.tenant_id, "result": saved})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def _saved_report_visual_types(value: Any, fallback: Any) -> dict[str, str]:
    """Permit owner-only presentation changes without accepting report data edits."""
    existing = fallback if isinstance(fallback, dict) else {}
    requested = value if isinstance(value, dict) else {}
    visual_types: dict[str, str] = {}
    for key in ("primary", "secondary"):
        candidate = str(requested.get(key) or existing.get(key) or "table").strip().lower()
        candidate = SAVED_REPORT_VISUAL_TYPE_ALIASES.get(candidate, candidate)
        if candidate not in SAVED_REPORT_VISUAL_TYPES:
            raise ValueError("saved_analysis_visual_type_invalid")
        visual_types[key] = candidate
    return visual_types


def handle_report_analysis_result_delete(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        result_id = first_query_value(params, "result_id")
        if not result_id:
            raise ValueError("result_id is required.")
        handler._require_report_permission(context, "create")
        deleted = handler.services.report_store.delete_analysis_result(
            context.tenant_id,
            result_id,
            actor_user_id=context.user_id,
        )
        handler._send_json({"tenant_id": context.tenant_id, "result_id": result_id, "deleted": deleted})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_report_analysis_result_save_weekly(handler: Any) -> None:
    """Share or unshare one saved analysis on the institution weekly report."""

    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_report_permission(context, "create")
        eligible = payload.get("weeklyReportEligible", True)
        if isinstance(eligible, str):
            eligible = eligible.strip().lower() not in {"0", "false", "no"}
        result_id = str(payload.get("result_id") or "")
        if eligible:
            result = _owned_saved_analysis(handler, context, result_id)
        else:
            result = handler.services.report_store.get_analysis_result(
                context.tenant_id, result_id, actor_user_id=context.user_id
            )
            if result is None:
                raise KeyError("saved_analysis_result_not_found")
            if not handler.services.permission_broker.enforcer.can_manage_shared_visual(
                context.user_id, context.tenant_id, str(result.get("ownerUserId") or "")
            ):
                raise PermissionError("saved_analysis_owner_required")
        hydrated = _hydrate_saved_analysis(handler, context.user_id, context.tenant_id, result)
        saved = handler.services.report_store.upsert_analysis_result(
            context.tenant_id,
            {
                **result,
                "topicData": hydrated.get("topicData") or result.get("topicData"),
                "weeklyReportEligible": bool(eligible),
                "weeklyReportSavedAt": datetime.now(timezone.utc).isoformat() if eligible else "",
                "visibility": "tenant" if eligible else "private",
            },
            updated_by=context.user_id,
        )
        saved_source = saved.get("source")
        source_channel = (
            str(saved_source.get("channel") or "self_analysis")
            if isinstance(saved_source, dict)
            else str(saved_source or "self_analysis")
        )
        handler._write_audit(
            context,
            "report.analysis.save_weekly",
            "saved_analysis_result",
            str(saved.get("id") or ""),
            {"source": source_channel},
        )
        handler._send_json({"tenant_id": context.tenant_id, "result": _hydrate_saved_analysis(handler, context.user_id, context.tenant_id, saved)})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_report_analysis_result_save_experience(handler: Any) -> None:
    """Persist an owner-scoped, evidence-backed experience-memory candidate."""

    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_report_permission(context, "create")
        handler._require_memory_permission(context, "create")
        result = _owned_saved_analysis(handler, context, str(payload.get("result_id") or ""))
        hydrated = _hydrate_saved_analysis(handler, context.user_id, context.tenant_id, result)
        topic_data = hydrated.get("topicData") if isinstance(hydrated.get("topicData"), dict) else {}
        rows = hydrated.get("rows") if isinstance(hydrated.get("rows"), list) else []
        content = {
            "kind": "saved_analysis_experience",
            "report": {
                "report_id": str(result.get("id") or ""),
                "title": str(result.get("title") or ""),
                "query": str(result.get("query") or ""),
                "plan": str(result.get("plan") or ""),
                "summary": str(hydrated.get("summary") or result.get("summary") or ""),
                "saved_at": str(result.get("savedAt") or ""),
                "source_channel": str((result.get("source") or {}).get("channel") or "self_analysis"),
            },
            "data_snapshot": {
                "topic_reference": {
                    "reference_type": str(topic_data.get("reference_type") or ""),
                    "reference_id": str(topic_data.get("reference_id") or ""),
                    "updated_at": str(topic_data.get("updated_at") or ""),
                },
                "row_count": int(topic_data.get("row_count") or len(rows)),
                "rows": rows,
            },
            "institution_scope": {
                "analysis_institution": str(result.get("analysisInstitution") or _institution_label(context.tenant_id)),
                "current_institution": str(result.get("currentInstitution") or _institution_label(context.tenant_id)),
                "uploaded_data_institutions": list(result.get("uploadedDataInstitutions") or []),
            },
        }
        content_hash = _stable_hash(content)
        analysis_tenant_id = _institution_tenant_id(
            str(content["institution_scope"]["analysis_institution"]), context.tenant_id
        )
        scopes = [(analysis_tenant_id, "analysis")]
        if analysis_tenant_id != context.tenant_id:
            # The same data-backed conclusion remains available from the
            # current institution for comparison, but each copy has an
            # explicit scope and is recalled only inside that scope.
            scopes.append((context.tenant_id, "current_location"))
        else:
            scopes = [(context.tenant_id, "analysis_and_current_location")]

        records: list[dict[str, Any]] = []
        idempotent = True
        unavailable_scopes: list[str] = []
        for memory_tenant_id, scope_role in scopes:
            if memory_tenant_id != context.tenant_id:
                try:
                    handler.services.permission_broker.require_resource(
                        ExecutionContext(user_id=context.user_id, tenant_id=memory_tenant_id),
                        "memory:*",
                        "create",
                    )
                except PermissionError:
                    unavailable_scopes.append(_institution_label(memory_tenant_id))
                    continue
            memory_id = f"mem_report_experience_{content_hash[:24]}_{scope_role}"
            memory_payload = {
                "memory_id": memory_id,
                "memory_type": "analysis_case",
                "subject_type": "user",
                "subject_id": context.user_id,
                "title": f"报告经验 · {str(result.get('title') or result.get('query') or '未命名报告')}",
                "content": {**content, "memory_scope_role": scope_role, "memory_tenant": _institution_label(memory_tenant_id)},
                "source_trace_id": str(result.get("analysisTaskId") or result.get("id") or ""),
                "confidence": 0.8,
                "evidence": {
                    "evidence_type": "saved_analysis_report",
                    "evidence_id": str(result.get("id") or ""),
                    "evidence_hash": _stable_hash({"content_hash": content_hash, "scope_role": scope_role}),
                },
            }
            try:
                record = handler.services.memory_service.create_candidate(
                    memory_tenant_id, memory_payload, context.user_id
                )
                idempotent = False
            except ValueError as exc:
                if str(exc) != "memory_candidate_rejected_or_duplicate":
                    raise
                record = handler.services.memory_service.get(memory_tenant_id, memory_id)
                if record.get("subject_type") != "user" or record.get("subject_id") != context.user_id:
                    raise PermissionError("memory_record_not_owned")
            records.append(record)
        if not records:
            raise PermissionError("analysis_memory_scope_unavailable")
        record = next((item for item in records if item.get("tenant_id") == context.tenant_id), records[0])
        handler._write_audit(
            context,
            "report.analysis.save_experience",
            "memory_record",
            str(record.get("memory_id") or ""),
            {
                "report_id": str(result.get("id") or ""),
                "content_hash": content_hash,
                "memory_tenants": [_institution_label(str(item.get("tenant_id") or "")) for item in records],
                "unavailable_tenants": unavailable_scopes,
            },
        )
        message = "已固化为当前账号的经验记忆候选；复核通过后才会参与后续召回。"
        if unavailable_scopes:
            message += f" 未在未授权机构写入经验：{'、'.join(unavailable_scopes)}。"
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                "record": record,
                "records": records,
                "idempotent": idempotent,
                "message": message,
            }
        )
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_report_comments_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        report_id = first_query_value(params, "report_id")
        if not report_id:
            raise ValueError("report_id is required.")
        handler._require_report_permission(context, "read")
        comments = handler.services.report_store.get_report_comments(context.tenant_id, report_id)
        revision = handler.services.report_store.get_comment_revision(context.tenant_id, report_id)
        handler._send_json(
            {"tenant_id": context.tenant_id, "report_id": report_id, "comments": comments, "revision": revision, "count": len(comments)}
        )
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_report_comments_replace(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        report_id = str(payload.get("report_id") or "").strip()
        comments = payload.get("comments")
        if not report_id:
            raise ValueError("report_id is required.")
        if not isinstance(comments, list):
            raise ValueError("comments must be a list.")
        handler._require_report_permission(context, "create")
        saved = handler.services.report_store.replace_report_comments(
            context.tenant_id,
            report_id,
            comments,
            updated_by=context.user_id,
            expected_revision=int(payload["expected_revision"]) if payload.get("expected_revision") is not None else None,
        )
        revision = handler.services.report_store.get_comment_revision(context.tenant_id, report_id)
        handler._send_json(
            {"tenant_id": context.tenant_id, "report_id": report_id, "comments": saved, "revision": revision, "count": len(saved)}
        )
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_report_comment_create(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        report_id = str(payload.get("report_id") or "").strip()
        draft = payload.get("comment")
        client_request_id = str(
            handler.headers.get("Idempotency-Key") or payload.get("client_request_id") or ""
        ).strip()
        if not report_id:
            raise ValueError("report_id is required.")
        if not isinstance(draft, dict):
            raise ValueError("comment must be an object.")
        if payload.get("expected_revision") is None:
            raise ValueError("expected_revision is required.")
        handler._require_report_permission(context, "create")
        result = handler.services.report_store.create_report_comment(
            context.tenant_id,
            report_id,
            draft,
            context.user_id,
            int(payload["expected_revision"]),
            client_request_id,
        )
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                "report_id": report_id,
                **result,
                "count": len(result["comments"]),
            }
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_report_comment_mutate(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        report_id = str(payload.get("report_id") or "").strip()
        comment_id = str(payload.get("comment_id") or "").strip()
        action = str(payload.get("action") or "").strip()
        action_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        client_request_id = str(
            handler.headers.get("Idempotency-Key") or payload.get("client_request_id") or ""
        ).strip()
        if not report_id or not comment_id:
            raise ValueError("report_id and comment_id are required.")
        if payload.get("expected_revision") is None:
            raise ValueError("expected_revision is required.")
        handler._require_report_permission(context, "create")
        result = handler.services.report_store.mutate_report_comment(
            context.tenant_id,
            report_id,
            comment_id,
            action,
            action_payload,
            context.user_id,
            int(payload["expected_revision"]),
            client_request_id,
        )
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                "report_id": report_id,
                **result,
                "count": len(result["comments"]),
            }
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_report_comment_delete(handler: Any, _query: str) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        report_id = str(payload.get("report_id") or "").strip()
        comment_id = str(payload.get("comment_id") or "").strip()
        if not report_id or not comment_id:
            raise ValueError("report_id and comment_id are required.")
        if payload.get("expected_revision") is None:
            raise ValueError("expected_revision is required.")
        handler._require_report_permission(context, "create")
        result = handler.services.report_store.mutate_report_comment(
            context.tenant_id,
            report_id,
            comment_id,
            "delete",
            {},
            context.user_id,
            int(payload["expected_revision"]),
        )
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                "report_id": report_id,
                **result,
                "count": len(result["comments"]),
            }
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_weekly_report_versions_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_report_permission(context, "read")
        handler.services.report_retention_service.enforce(context.tenant_id)
        versions = handler.services.report_store.list_weekly_report_versions(context.tenant_id, actor_user_id=context.user_id)
        tasks = handler.services.report_store.list_weekly_ai_tasks(context.tenant_id)
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                "versions": versions,
                "analysis_tasks": tasks,
                "count": len(versions),
            }
        )
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_weekly_report_version_save(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        version = payload.get("version")
        if not isinstance(version, dict):
            raise ValueError("version must be an object.")
        handler._require_report_permission(context, "create")
        handler.services.report_retention_service.enforce(context.tenant_id)
        bound_version = _bind_weekly_report_evidence(handler, context, version)
        saved = handler.services.report_store.save_weekly_report_version(
            context.tenant_id,
            bound_version,
            updated_by=context.user_id,
        )
        for evidence_ref in bound_version.get("analysisEvidenceRefs", []):
            if not isinstance(evidence_ref, dict) or not evidence_ref.get("evidence_id"):
                continue
            handler.services.lineage_store.record_edge(
                context.tenant_id,
                {
                    "source_type": "analysis_evidence",
                    "source_id": str(evidence_ref["evidence_id"]),
                    "target_type": "weekly_report_version",
                    "target_id": str(saved["id"]),
                    "edge_type": "publishes",
                    "expression_hash": str(evidence_ref.get("evidence_hash") or ""),
                    "metadata": {"report_id": saved.get("reportId")},
                },
                context.user_id,
            )
        analyze = payload.get("analyze", True)
        task = None
        if analyze is not False:
            task = _weekly_learning_engine(handler).analyze_version(
                context.tenant_id,
                saved["id"],
                context.user_id,
                force=bool(payload.get("force")),
            )
        handler._write_audit(context, "weekly_report.version.save", "weekly_report_version", saved["id"])
        handler._send_json({"tenant_id": context.tenant_id, "version": saved, "analysis_task": task})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_weekly_report_version_analyze(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        version_id = str(payload.get("version_id") or payload.get("versionId") or "").strip()
        if not version_id:
            raise ValueError("version_id is required.")
        handler._require_report_permission(context, "create")
        task = _weekly_learning_engine(handler).analyze_version(
            context.tenant_id,
            version_id,
            context.user_id,
            force=bool(payload.get("force", True)),
        )
        handler._write_audit(context, "weekly_report.version.analyze", "weekly_report_version", version_id)
        handler._send_json({"tenant_id": context.tenant_id, "analysis_task": task})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_weekly_report_learning_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        version_id = first_query_value(params, "version_id")
        handler._require_report_permission(context, "read")
        if version_id:
            task = handler.services.report_store.get_weekly_ai_task(context.tenant_id, version_id)
            candidates = [
                item for item in handler.services.report_store.list_learning_candidates(context.tenant_id)
                if item.get("version_id") == version_id
            ]
            handler._send_json({"tenant_id": context.tenant_id, "analysis_task": task, "learning_candidates": candidates})
            return
        tasks = handler.services.report_store.list_weekly_ai_tasks(context.tenant_id)
        candidates = handler.services.report_store.list_learning_candidates(context.tenant_id)
        handler._send_json(
            {"tenant_id": context.tenant_id, "analysis_tasks": tasks, "learning_candidates": candidates, "count": len(tasks)}
        )
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_weekly_report_learning_review(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_report_permission(context, "manage")
        candidate_id = str(payload.get("learning_candidate_id") or "").strip()
        decision = str(payload.get("decision") or "").strip()
        candidate = handler.services.report_store.review_learning_candidate(
            context.tenant_id,
            candidate_id,
            decision,
            context.user_id,
        )
        applied = None
        if decision == "approve":
            applied = _apply_learning_candidate(handler, context, candidate)
            candidate = handler.services.report_store.mark_learning_candidate_applied(
                context.tenant_id,
                candidate_id,
            )
        handler._write_audit(
            context,
            "weekly_report.learning.review",
            "report_learning_candidate",
            candidate_id,
            {"decision": decision, "status": candidate["status"], "content_hash": candidate["content_hash"]},
        )
        handler._send_json(
            {"tenant_id": context.tenant_id, "learning_candidate": candidate, "applied_result": applied}
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def _weekly_learning_engine(handler: Any) -> WeeklyReportLearningEngine:
    return WeeklyReportLearningEngine(
        handler.services.report_store,
        handler.services.data_asset_store,
        handler.services.application_store,
    )


def _hydrate_saved_analysis(handler: Any, user_id: str, tenant_id: str, result: dict[str, Any]) -> dict[str, Any]:
    task_id = str(result.get("analysisTaskId") or "")
    try:
        task = handler.services.task_repository.get_task(task_id) if task_id else None
    except KeyError:
        task = None
    if not task or task.get("tenant_id") != tenant_id:
        report_id = str(result.get("id") or "").strip()
        existing_reference = result.get("topicData") if isinstance(result.get("topicData"), dict) else None
        if existing_reference and existing_reference.get("reference_type") == "report":
            report_reference = existing_reference
        else:
            report_reference = handler.services.topic_data_store.record_saved_report_snapshot(
                tenant_id=tenant_id,
                user_id=user_id,
                report_id=report_id,
                report=result,
            )
            # The migration is durable: subsequent title edits use this
            # server-authored reference and never need the legacy row payload.
            result = handler.services.report_store.upsert_analysis_result(
                tenant_id,
                {**result, "topicData": report_reference},
                updated_by=user_id,
            )
        try:
            topic_data = handler.services.topic_data_store.read_reference(
                tenant_id=tenant_id,
                user_id=user_id,
                reference_type="report",
                reference_id=report_id,
                data_type="data",
            )
        except (KeyError, ValueError, PermissionError):
            return {**result, "rows": [], "execution_status": "unavailable"}
        return {
            **result,
            "rows": topic_data["rows"],
            "topicData": report_reference,
            "execution_status": "legacy_snapshot",
        }
    try:
        topic_data = handler.services.topic_data_store.read_reference(
            tenant_id=tenant_id,
            user_id=user_id,
            reference_type="history",
            reference_id=task_id,
            data_type="data",
        )
    except (KeyError, ValueError, PermissionError):
        topic_data = handler.services.topic_data_store.record_analysis_execution(
            tenant_id=tenant_id,
            user_id=user_id,
            task=task,
        )["history"]
        topic_data = handler.services.topic_data_store.read_reference(
            tenant_id=tenant_id,
            user_id=user_id,
            reference_type="history",
            reference_id=task_id,
            data_type="data",
        )
    return {
        **result,
        "rows": topic_data["rows"],
        "topicData": {
            "reference_type": "history",
            "reference_id": task_id,
            "folder": topic_data["folder"],
            "updated_at": str(topic_data.get("manifest", {}).get("created_at") or ""),
            "row_count": topic_data["row_count"],
            "has_data": True,
            "version_count": 1,
        },
        "execution_status": task.get("status"),
        "execution_id": task.get("execution_id"),
        "publication_gate": (task.get("review") or {}).get("publication_gate"),
    }


def _owned_saved_analysis(handler: Any, context: Any, result_id: str) -> dict[str, Any]:
    normalized_id = str(result_id or "").strip()
    if not normalized_id:
        raise ValueError("result_id is required.")
    result = handler.services.report_store.get_analysis_result(
        context.tenant_id,
        normalized_id,
        actor_user_id=context.user_id,
    )
    if result is None:
        raise KeyError("saved_analysis_result_not_found")
    if str(result.get("ownerUserId") or "") != context.user_id:
        raise PermissionError("saved_analysis_owner_required")
    return result


def _bind_weekly_report_evidence(handler: Any, context: Any, version: dict[str, Any]) -> dict[str, Any]:
    bound = json.loads(json.dumps(version, ensure_ascii=False))
    bound_refs: list[dict[str, Any]] = []
    raw_refs = bound.get("analysisTaskRefs") if isinstance(bound.get("analysisTaskRefs"), list) else []
    for raw_task_id in raw_refs[:50]:
        task_id = str(raw_task_id or "").strip()
        task = handler.services.task_repository.get_task(task_id) if task_id else None
        if not task or task.get("tenant_id") != context.tenant_id or task.get("user_id") != context.user_id:
            continue
        skill_results = task.get("skill_results") if isinstance(task.get("skill_results"), list) else []
        result = skill_results[0] if skill_results and isinstance(skill_results[0], dict) else {}
        evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
        bound_refs.append(
            {
                "analysis_task_id": task_id,
                "execution_id": task.get("execution_id"),
                "evidence_id": evidence.get("evidence_id"),
                "evidence_hash": _stable_hash(evidence) if evidence else "",
                "review_status": (task.get("review") or {}).get("status") if isinstance(task.get("review"), dict) else "",
            }
        )
    bound["analysisEvidenceRefs"] = bound_refs
    report = bound.get("report") if isinstance(bound.get("report"), dict) else {}
    for section in report.get("sections", []) if isinstance(report.get("sections"), list) else []:
        if not isinstance(section, dict):
            continue
        for block in section.get("blocks", []) if isinstance(section.get("blocks"), list) else []:
            if not isinstance(block, dict) or block.get("type") != "table":
                continue
            task_id = str(block.get("analysisTaskId") or block.get("analysis_task_id") or "").strip()
            if not task_id:
                block["evidenceRef"] = {
                    "verified": False,
                    "reason": "analysis_task_reference_missing",
                }
                continue
            task = handler.services.task_repository.get_task(task_id)
            if not task or task.get("tenant_id") != context.tenant_id or task.get("user_id") != context.user_id:
                block["evidenceRef"] = {"verified": False, "reason": "analysis_task_not_owned"}
                continue
            skill_results = task.get("skill_results") if isinstance(task.get("skill_results"), list) else []
            result = skill_results[0] if skill_results and isinstance(skill_results[0], dict) else {}
            evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
            semantic = result.get("semantic_info") if isinstance(result.get("semantic_info"), dict) else {}
            task_rows = result.get("data") if isinstance(result.get("data"), list) else []
            block_rows = block.get("rows") if isinstance(block.get("rows"), list) else []
            rows_match = _stable_hash(block_rows) == _stable_hash(task_rows)
            review = task.get("review") if isinstance(task.get("review"), dict) else {}
            verified = bool(
                task.get("status") == "completed"
                and review.get("status") == "passed"
                and semantic.get("execution_mode") == "real"
                and semantic.get("publishable") is True
                and evidence.get("evidence_id")
                and evidence.get("source_snapshot")
                and rows_match
            )
            block["evidenceRef"] = {
                "verified": verified,
                "reason": "verified" if verified else "execution_or_rows_not_publishable",
                "analysis_task_id": task_id,
                "execution_id": task.get("execution_id"),
                "evidence_id": evidence.get("evidence_id"),
                "evidence_hash": _stable_hash(evidence) if evidence else "",
                "rows_hash": _stable_hash(task_rows),
                "source_snapshot": evidence.get("source_snapshot") if isinstance(evidence.get("source_snapshot"), dict) else {},
                "data_source": evidence.get("data_source"),
            }
    bound["report"] = report
    return bound


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _apply_learning_candidate(handler: Any, context: Any, candidate: dict[str, Any]) -> dict[str, Any]:
    candidate_type = str(candidate["candidate_type"])
    content = candidate.get("candidate_content") if isinstance(candidate.get("candidate_content"), dict) else {}
    evidence_summary = candidate.get("evidence_summary") if isinstance(candidate.get("evidence_summary"), dict) else {}
    if candidate_type == "analysis_method":
        item = {
            **content,
            "enabled": True,
            "status": "当前有效",
            "sourceVersionId": candidate["version_id"],
            "reviewedBy": context.user_id,
        }
        return handler.services.data_asset_store.upsert_item(
            context.tenant_id,
            "analysis_experience",
            item,
            updated_by=context.user_id,
            lifecycle_status="active",
        )
    if candidate_type in {"behavior_habit", "business_fact"}:
        if candidate_type == "business_fact" and evidence_summary.get("publishable") is not True:
            raise ValueError("publishable_report_evidence_required_for_business_fact")
        memory_id = f"mem_{uuid4().hex}"
        evidence_hash = str(candidate.get("content_hash") or _stable_hash(evidence_summary))
        record = MemoryRecord(
            memory_id=memory_id,
            memory_type="behavior_habit" if candidate_type == "behavior_habit" else "business_fact",
            tenant_id=context.tenant_id,
            subject=str(content.get("title") or candidate_type),
            title=str(content.get("title") or candidate_type),
            content=content,
            confidence=float(candidate.get("confidence") or 0),
            verified_status="active",
            subject_type="user" if candidate_type == "behavior_habit" else "tenant",
            subject_id=str(candidate.get("created_by") or context.user_id) if candidate_type == "behavior_habit" else context.tenant_id,
            evidence_type="weekly_report_version",
            evidence_id=str(candidate["version_id"]),
            evidence_hash=evidence_hash,
            created_by=context.user_id,
        )
        if not handler.services.memory_store.write(record, force=True):
            raise ValueError("learning_memory_duplicate")
        return handler.services.memory_store.get(context.tenant_id, memory_id)
    if candidate_type == "todo":
        todo_payload = content if isinstance(content.get("todo"), dict) else {"todo": content}
        todo_payload = dict(todo_payload)
        profile = handler.services.access_service.user_store.get_profile(context.user_id)
        todo_payload["actorDisplayName"] = str(getattr(profile, "name", "") or "当前用户").strip()
        governed_todo = dict(todo_payload.get("todo") or {})
        governed_todo.update(
            source="weekly_report",
            sourceVersionId=str(candidate["version_id"]),
            sourceText=str(content.get("sourceText") or content.get("description") or "")[:1200],
            confidence=float(candidate.get("confidence") or 0),
        )
        todo_payload["todo"] = governed_todo
        result = handler.services.application_store.run_action(
            context.tenant_id,
            "agent_workspace",
            "create_todo",
            todo_payload,
            actor_user_id=context.user_id,
            trusted_provenance=True,
        )
        return result.get("result", {})
    raise ValueError("unsupported_learning_candidate_type")
