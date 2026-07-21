from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4
from urllib.parse import parse_qs

from backend.platform.api.support import first_query_value, send_route_exception
from backend.platform.memory import MemoryRecord
from backend.platform.reports.weekly_learning import WeeklyReportLearningEngine


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
        task = handler.services.task_repository.get_task(task_id) if task_id else None
        if not task or task.get("tenant_id") != context.tenant_id or task.get("user_id") != context.user_id:
            raise PermissionError("saved analysis must reference an owned execution")
        result = {
            **result,
            "analysisTaskId": task_id,
            "ownerUserId": context.user_id,
            "visibility": str(result.get("visibility") or "private"),
        }
        saved = handler.services.report_store.upsert_analysis_result(
            context.tenant_id,
            result,
            updated_by=context.user_id,
        )
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
    task = handler.services.task_repository.get_task(task_id) if task_id else None
    if not task or task.get("tenant_id") != tenant_id:
        return {**result, "rows": [], "execution_status": "unavailable"}
    skill_results = task.get("skill_results") if isinstance(task.get("skill_results"), list) else []
    first = skill_results[0] if skill_results and isinstance(skill_results[0], dict) else {}
    return {
        **result,
        "rows": [dict(row) for row in first.get("data", []) if isinstance(row, dict)][:200],
        "execution_status": task.get("status"),
        "execution_id": task.get("execution_id"),
        "publication_gate": (task.get("review") or {}).get("publication_gate"),
    }


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
