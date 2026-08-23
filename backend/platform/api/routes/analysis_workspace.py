from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.platform.analysis_workspace.models import AnalysisWorkspaceContext
from backend.platform.analysis_workspace.service import (
    build_trusted_manifest,
    manifest_has_display_provenance,
    provenance_dataset_snapshot,
    provenance_metric_versions,
    verify_trusted_manifest,
)
from backend.platform.analysis_workspace.visualization import VisualizationPlanner
from backend.platform.api.support import first_query_value, send_route_exception


def handle_analysis_workspaces_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler.services.permission_broker.require_skill(context.to_execution_context(), "supersonic.query")
        workspace_id = first_query_value(params, "workspace_id")
        workspace = handler.services.analysis_workspace_service.workspace(context.tenant_id, context.user_id, workspace_id)
        threads = handler.services.analysis_workspace_service.threads(context.tenant_id, context.user_id, workspace_id)
        handler._send_json({"workspace": workspace, "threads": threads})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_analysis_workspace_upsert(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler.services.permission_broker.require_skill(context.to_execution_context(), "supersonic.query")
        workspace_context = _workspace_context(payload.get("context"))
        workspace = handler.services.analysis_workspace_service.ensure_workspace(
            context.tenant_id,
            context.user_id,
            str(payload.get("workspace_key") or workspace_context.page_key),
            workspace_context,
        )
        handler._write_audit(context, "analysis.workspace.upsert", "analysis_workspace", str(workspace["workspace_id"]), {"page_key": workspace_context.page_key})
        handler._send_json({"workspace": workspace})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_analysis_thread_branch(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler.services.permission_broker.require_skill(context.to_execution_context(), "supersonic.query")
        thread = handler.services.analysis_workspace_service.branch(
            context.tenant_id,
            context.user_id,
            str(payload.get("workspace_id") or ""),
            parent_thread_id=str(payload.get("parent_thread_id") or "") or None,
            title=str(payload.get("title") or "分析分支"),
            anchor=payload.get("anchor") if isinstance(payload.get("anchor"), dict) else {},
        )
        handler._write_audit(context, "analysis.thread.branch", "analysis_thread", str(thread["thread_id"]), {"workspace_id": thread["workspace_id"]})
        handler._send_json({"thread": thread})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_analysis_turn_append(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler.services.permission_broker.require_skill(context.to_execution_context(), "supersonic.query")
        turn = handler.services.analysis_workspace_service.append_turn(
            context.tenant_id,
            context.user_id,
            str(payload.get("thread_id") or ""),
            payload,
        )
        handler._write_audit(context, "analysis.turn.append", "analysis_turn", str(turn["turn_id"]), {"thread_id": turn["thread_id"], "status": turn["status"]})
        handler._send_json({"turn": turn})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_analysis_thread_archive(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler.services.permission_broker.require_skill(context.to_execution_context(), "supersonic.query")
        thread = handler.services.analysis_workspace_service.archive_thread(
            context.tenant_id,
            context.user_id,
            str(payload.get("thread_id") or ""),
        )
        handler._write_audit(context, "analysis.thread.archive", "analysis_thread", str(thread["thread_id"]), {"workspace_id": thread.get("workspace_id")})
        handler._send_json({"thread": thread})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_analysis_threads_merge(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler.services.permission_broker.require_skill(context.to_execution_context(), "supersonic.query")
        source_ids = payload.get("source_thread_ids")
        if not isinstance(source_ids, list):
            raise ValueError("source_thread_ids_required")
        result = handler.services.analysis_workspace_service.merge(
            context.tenant_id,
            context.user_id,
            str(payload.get("target_thread_id") or ""),
            [str(item) for item in source_ids],
            question=str(payload.get("question") or "合并分支结论"),
            answer=str(payload.get("answer") or ""),
            evidence_refs=payload.get("evidence_refs") if isinstance(payload.get("evidence_refs"), list) else [],
        )
        handler._write_audit(context, "analysis.thread.merge", "analysis_thread", result["target_thread_id"], {"source_thread_ids": result["source_thread_ids"]})
        handler._send_json(result)
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_analysis_visualization_plan(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler.services.permission_broker.require_skill(context.to_execution_context(), "supersonic.query")
        rows = payload.get("rows")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows) or len(rows) > 2_000:
            raise ValueError("visualization_rows_invalid")
        spec = VisualizationPlanner().plan(
            question=str(payload.get("question") or ""),
            rows=rows,
            dimensions=_strings(payload.get("dimensions"), 20),
            metrics=_strings(payload.get("metrics"), 20),
            intent=payload.get("intent") if isinstance(payload.get("intent"), dict) else {},
            proposed_chart_types=_strings(payload.get("proposed_chart_types"), 8),
        )
        handler._send_json({"visualization": spec.payload()})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_analysis_artifact_trust(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler.services.permission_broker.require_skill(context.to_execution_context(), "supersonic.query")
        task_id = first_query_value(params, "task_id")
        task = handler.services.task_repository.get_task(task_id)
        if not task or str(task.get("tenant_id")) != context.tenant_id or str(task.get("user_id")) != context.user_id:
            raise PermissionError("analysis_task_not_owned")
        result = ((task.get("skill_results") or [{}])[0]) if isinstance(task.get("skill_results"), list) else {}
        stored_manifest = result.get("trusted_manifest") if isinstance(result, dict) else None
        if isinstance(stored_manifest, dict) and verify_trusted_manifest(stored_manifest) and manifest_has_display_provenance(stored_manifest):
            handler._send_json({"manifest": stored_manifest})
            return
        if isinstance(stored_manifest, dict) and stored_manifest and not verify_trusted_manifest(stored_manifest):
            raise RuntimeError("trusted_manifest_hash_mismatch")
        evidence = result.get("evidence") if isinstance(result, dict) and isinstance(result.get("evidence"), dict) else {}
        semantic = result.get("semantic_info") if isinstance(result, dict) and isinstance(result.get("semantic_info"), dict) else {}
        asset_context = task.get("asset_context") if isinstance(task.get("asset_context"), dict) else {}
        result_rows = result.get("data") if isinstance(result, dict) and isinstance(result.get("data"), list) else []
        manifest = build_trusted_manifest(
            tenant_id=context.tenant_id,
            artifact_id=str(task.get("execution_id") or task_id),
            dataset_snapshot=provenance_dataset_snapshot(
                semantic.get("source_snapshot"),
                evidence.get("source_snapshot"),
                stored_manifest.get("dataset_snapshot") if isinstance(stored_manifest, dict) else {},
                *_objects(asset_context.get("selected_data_tables")),
                schema_material=[semantic.get("schema_mapping"), result_rows],
                content_material=result_rows,
            ),
            metric_versions=provenance_metric_versions(
                semantic.get("metric_versions"),
                evidence.get("metric_versions"),
                asset_context.get("metric_dictionary_definitions"),
                stored_manifest.get("metric_versions") if isinstance(stored_manifest, dict) else [],
            ),
            sql=str(evidence.get("executed_sql") or ""),
            result=result_rows,
            visualization=result.get("visualization_spec") if isinstance(result, dict) and isinstance(result.get("visualization_spec"), dict) else {},
            skill_versions=task.get("skill_versions") if isinstance(task.get("skill_versions"), list) else [],
            model_version=str(task.get("selected_model") or ""),
            authorization_snapshot=semantic.get("metric_access") if isinstance(semantic.get("metric_access"), dict) else {},
            evidence_refs=[evidence] if evidence else [],
            evaluation=task.get("review") if isinstance(task.get("review"), dict) else {},
        )
        handler._send_json({"manifest": manifest})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_analysis_execution_nodes(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler.services.permission_broker.require_skill(context.to_execution_context(), "supersonic.query")
        task_id = first_query_value(params, "task_id")
        task = handler.services.task_repository.get_task(task_id)
        if not task or str(task.get("tenant_id")) != context.tenant_id or str(task.get("user_id")) != context.user_id:
            raise PermissionError("analysis_task_not_owned")
        nodes = handler.services.task_repository.execution_nodes(
            context.tenant_id,
            context.user_id,
            task_id,
        )
        handler._send_json({"task_id": task_id, "nodes": nodes, "count": len(nodes)})
    except Exception as exc:
        send_route_exception(handler, exc)


def _workspace_context(value: Any) -> AnalysisWorkspaceContext:
    payload = value if isinstance(value, dict) else {}
    page_key = str(payload.get("page_key") or payload.get("pageKey") or "").strip()
    if not page_key:
        raise ValueError("page_key_required")
    return AnalysisWorkspaceContext(
        page_key=page_key,
        artifact_id=str(payload.get("artifact_id") or payload.get("artifactId") or ""),
        dataset_snapshot=payload.get("dataset_snapshot") if isinstance(payload.get("dataset_snapshot"), dict) else payload.get("datasetSnapshot") if isinstance(payload.get("datasetSnapshot"), dict) else {},
        metric_versions=tuple(payload.get("metric_versions") if isinstance(payload.get("metric_versions"), list) else payload.get("metricVersions") if isinstance(payload.get("metricVersions"), list) else []),
        filters=payload.get("filters") if isinstance(payload.get("filters"), dict) else {},
        selected_data_point=payload.get("selected_data_point") if isinstance(payload.get("selected_data_point"), dict) else payload.get("selectedDataPoint") if isinstance(payload.get("selectedDataPoint"), dict) else None,
        allowed_actions=tuple(_strings(payload.get("allowed_actions") or payload.get("allowedActions"), 20)),
        evidence_refs=tuple(payload.get("evidence_refs") if isinstance(payload.get("evidence_refs"), list) else payload.get("evidenceRefs") if isinstance(payload.get("evidenceRefs"), list) else []),
    )


def _strings(value: Any, limit: int) -> list[str]:
    return [str(item).strip()[:160] for item in value[:limit] if str(item or "").strip()] if isinstance(value, list) else []


def _objects(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []
