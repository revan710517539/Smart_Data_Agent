from __future__ import annotations

import base64
import binascii
from typing import Any
from urllib.parse import parse_qs
from uuid import uuid4

from backend.platform.api.support import first_query_value, send_route_exception


RUNTIME_CONFIGURATION_ASSET_TYPES = frozenset({
    "analysis_skill",
    "external_tool",
    "analysis_shortcut",
})


def handle_data_assets_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_asset_permission(context, "read")
        scope = str((params.get("scope") or [""])[0]).strip().lower()
        if scope == "knowledge":
            bundle = handler.services.data_asset_store.list_bundle(context.tenant_id)
            bundle["raw_tables"] = []
            bundle["topic_tables"] = []
            handler._send_json({"tenant_id": context.tenant_id, **bundle, "source_mode": "knowledge_only", "count": {key: len(value) for key, value in bundle.items()}})
            return
        csv_catalog = handler.services.data_acquisition_service.csv_source.for_tenant(context.tenant_id)
        if not csv_catalog.catalog_ready:
            handler._send_json(
                {
                    "tenant_id": context.tenant_id,
                    "status": "loading",
                    "message": "当前机构的 Data Crawler 原始数据目录正在准备中，请稍候重试。",
                    "source_mode": "csv_folder",
                },
                headers={"Retry-After": "1"},
            )
            return
        bundle = handler.services.data_asset_store.list_bundle(context.tenant_id)
        bundle["external_tools"] = [
            item
            for item in bundle.get("external_tools", [])
            if str(item.get("toolType") or "").casefold() not in {"browser_collector", "page_collector"}
        ]
        csv_source = csv_catalog.snapshot()
        # Raw tables are generated only from the selected institution's
        # Data Crawler directory. Never merge or fall back to another tenant.
        # Do not merge in legacy stored raw-table records: they may describe a
        # deleted upload or retired external source and would make the data
        # management page disagree with the analysis picker.
        bundle["raw_tables"] = csv_catalog.table_assets()
        topic_snapshots = handler.services.topic_data_store.topic_table_snapshots(
            context.tenant_id,
            [str(item.get("id") or "") for item in bundle.get("topic_tables", []) if item.get("id")],
        )
        bundle["topic_tables"] = [
            {**item, "dataSnapshot": topic_snapshots.get(str(item.get("id") or ""))}
            for item in bundle.get("topic_tables", [])
        ]
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                **bundle,
                "source_mode": "csv_folder",
                "source_read_only": True,
                "csv_source": csv_source,
                "count": {key: len(value) for key, value in bundle.items()},
            }
        )
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_data_asset_item_upsert(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        item_type = str(payload.get("item_type") or "").strip()
        item = payload.get("item")
        if not isinstance(item, dict):
            raise ValueError("item must be an object.")
        handler._require_asset_permission(context, "create")
        item = dict(item)
        requested_id = str(item.get("id") or "").strip()
        existing = (
            handler.services.data_asset_store.get_item(context.tenant_id, item_type, requested_id)
            if requested_id
            else None
        )
        if existing:
            expected_lock_version = payload.get("expected_lock_version", item.get("lockVersion"))
            if expected_lock_version is None or int(expected_lock_version) != int(existing.get("lockVersion") or 0):
                raise RuntimeError("data_asset_lock_version_conflict")
        else:
            item["id"] = f"asset_{uuid4().hex}"
        for untrusted_field in (
            "lifecycleStatus",
            "assetVersion",
            "schemaVersion",
            "lockVersion",
            "submittedBy",
            "reviewedBy",
            "reviewedAt",
            "publishedAt",
        ):
            item.pop(untrusted_field, None)
        if item_type in {"topic_table", "analysis_experience"} and item.get("analysisTaskId"):
            item = _bind_analysis_asset(handler, context, item_type, item)
        saved = handler.services.data_asset_store.upsert_item(
            context.tenant_id,
            item_type,
            item,
            updated_by=context.user_id,
            # These three records are operational configuration, not analytical
            # truth data. Authorized maintainers expect save/toggle actions to
            # take effect immediately. They remain versioned and audited.
            lifecycle_status="active" if item_type in RUNTIME_CONFIGURATION_ASSET_TYPES else "review",
        )
        if item_type == "topic_table" and item.get("analysisTaskId"):
            task = handler.services.task_repository.get_task(str(item["analysisTaskId"]))
            if task:
                snapshot = handler.services.topic_data_store.record_topic_table_snapshot(
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                    topic_table_id=str(saved.get("id") or ""),
                    task=task,
                )
                saved = {**saved, "dataSnapshot": snapshot}
        handler._write_audit(context, "data_asset.item.upsert", item_type, str(saved.get("id") or ""))
        handler._send_json({"tenant_id": context.tenant_id, "item_type": item_type, "item": saved})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_data_asset_raw_file_upload(handler: Any) -> None:
    try:
        payload = handler._read_json(max_bytes=12 * 1024 * 1024)
        context = handler._request_context(payload=payload)
        handler._require_asset_permission(context, "create")
        encoded = str(payload.get("content_base64") or payload.get("contentBase64") or "").strip()
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("invalid_content_base64") from exc
        result = handler.services.data_acquisition_service.upload_raw_asset_file(
            context.tenant_id,
            str(payload.get("file_name") or payload.get("fileName") or ""),
            content,
            context.user_id,
        )
        handler._write_audit(
            context,
            "data_asset.raw_file.upload",
            "raw_file",
            str(result.get("artifact_id") or ""),
            {
                "file_name": result.get("file_name"),
                "content_hash": result.get("content_hash"),
                "size_bytes": result.get("size_bytes"),
            },
        )
        handler._send_json({"tenant_id": context.tenant_id, "file": result})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_topic_data_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_asset_permission(context, "read")
        reference_type = first_query_value(params, "reference_type")
        reference_id = first_query_value(params, "reference_id")
        data_type = first_query_value(params, "data_type") or "data"
        if reference_type == "topic":
            topic = handler.services.data_asset_store.get_item(context.tenant_id, "topic_table", reference_id)
            if topic is None:
                raise PermissionError("topic_table_unavailable")
        elif reference_type == "report":
            report = handler.services.report_store.get_analysis_result(
                context.tenant_id,
                reference_id,
                actor_user_id=context.user_id,
            )
            if report is None:
                raise PermissionError("saved_report_unavailable")
        result = handler.services.topic_data_store.read_reference(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            reference_type=reference_type,
            reference_id=reference_id,
            data_type=data_type,
        )
        handler._send_json({"tenant_id": context.tenant_id, **result})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def _bind_analysis_asset(handler: Any, context: Any, item_type: str, item: dict[str, Any]) -> dict[str, Any]:
    task_id = str(item.get("analysisTaskId") or "").strip()
    task = handler.services.task_repository.get_task(task_id)
    if not task or task.get("tenant_id") != context.tenant_id or task.get("user_id") != context.user_id:
        raise PermissionError("analysis_task_unavailable_for_asset")
    results = task.get("skill_results") if isinstance(task.get("skill_results"), list) else []
    result = results[0] if results and isinstance(results[0], dict) else {}
    semantic = result.get("semantic_info") if isinstance(result.get("semantic_info"), dict) else {}
    evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
    review = task.get("review") if isinstance(task.get("review"), dict) else {}
    publishable = bool(
        task.get("status") == "completed"
        and review.get("status") == "passed"
        and review.get("publication_gate") == "allowed"
        and semantic.get("execution_mode") == "real"
        and semantic.get("publishable") is True
        and evidence.get("evidence_id")
        and isinstance(evidence.get("source_snapshot"), dict)
        and evidence.get("source_snapshot")
        and evidence.get("sql_executed") is True
    )
    if not publishable:
        raise ValueError("publishable_analysis_evidence_required_for_asset")
    bound = {
        **item,
        "analysisTaskId": task_id,
        "executionId": str(task.get("execution_id") or task_id),
        "evidenceId": str(evidence.get("evidence_id") or ""),
        "sourceSnapshot": evidence.get("source_snapshot"),
    }
    if item_type == "topic_table":
        bound["sql"] = _detail_query_from_execution(str(evidence.get("executed_sql") or ""))
        rows = result.get("data") if isinstance(result.get("data"), list) else []
        if rows and isinstance(rows[0], dict):
            requested_fields = bound.get("fields") if isinstance(bound.get("fields"), list) else []
            requested_names = {
                str(field.get("fieldNameEn") or "")
                for field in requested_fields
                if isinstance(field, dict)
            }
            actual_names = set(rows[0])
            if not requested_names or not requested_names.issubset(actual_names):
                raise ValueError("topic_table_fields_do_not_match_executed_result")
    else:
        bound["sourceVersionId"] = task_id
        bound["evidence"] = f"analysis_evidence:{evidence.get('evidence_id')}"
    return bound


def _detail_query_from_execution(executed_sql: str) -> str:
    sql = executed_sql.strip()
    if not sql:
        raise ValueError("executed_sql_required_for_topic_table")
    if sql.startswith("-- detail query"):
        sql = sql[len("-- detail query"):].lstrip()
        sql = sql.split(";", 1)[0].strip()
    elif ";" in sql.rstrip(";"):
        raise ValueError("topic_table_requires_single_executed_query")
    return sql.rstrip(";").strip()


def handle_data_asset_item_review(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_asset_permission(context, "manage")
        item_type = str(payload.get("item_type") or "").strip()
        item_id = str(payload.get("item_id") or "").strip()
        decision = str(payload.get("decision") or "").strip()
        if not item_type or not item_id:
            raise ValueError("item_type and item_id are required.")
        reviewed = handler.services.data_asset_store.review_item(
            context.tenant_id,
            item_type,
            item_id,
            decision=decision,
            reviewer_user_id=context.user_id,
            comments=str(payload.get("comments") or ""),
            expected_version=int(payload["expected_version"]) if payload.get("expected_version") is not None else None,
        )
        handler._write_audit(
            context,
            "data_asset.item.review",
            item_type,
            item_id,
            {"decision": decision, "version": reviewed.get("assetVersion")},
        )
        handler._send_json({"tenant_id": context.tenant_id, "item_type": item_type, "item": reviewed})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_data_asset_item_delete(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        item_type = first_query_value(params, "item_type")
        item_id = first_query_value(params, "item_id")
        if not item_type or not item_id:
            raise ValueError("item_type and item_id are required.")
        handler._require_asset_permission(context, "create")
        deleted = handler.services.data_asset_store.delete_item(context.tenant_id, item_type, item_id)
        handler._write_audit(context, "data_asset.item.delete", item_type, item_id, {"deleted": deleted})
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                "item_type": item_type,
                "item_id": item_id,
                "deleted": deleted,
            }
        )
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)
