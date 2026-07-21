from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs
from uuid import uuid4

from backend.platform.api.support import first_query_value, send_route_exception


def handle_data_acquisition_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_asset_permission(context, "read")
        bundle = handler.services.data_acquisition_service.bundle(context.tenant_id)
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                **bundle,
                "count": {key: len(value) for key, value in bundle.items()},
            }
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_acquisition_sql_parse(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_asset_permission(context, "read")
        sql = str(payload.get("sql") or "").strip()
        dialect = str(payload.get("dialect") or "postgres").strip()
        decomposition = handler.services.topic_metadata_service.parse_sql(sql, dialect)
        handler._send_json({"tenant_id": context.tenant_id, "decomposition": decomposition})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_acquisition_metadata_refresh(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_asset_permission(context, "create")
        topic_table_id = str(payload.get("topic_table_id") or "").strip()
        if not topic_table_id:
            raise ValueError("topic_table_id_required")
        result = handler.services.topic_metadata_service.refresh(
            context.tenant_id,
            topic_table_id,
            context.user_id,
            connection_id=str(payload.get("connection_id") or "").strip() or None,
            cascade=bool(payload.get("cascade")),
            dialect=str(payload.get("dialect") or "postgres"),
        )
        handler._write_audit(
            context,
            "data_acquisition.metadata.refresh",
            "topic_table",
            topic_table_id,
            {"status": result.get("status"), "cascade": result.get("cascade"), "table_count": len(result.get("raw_tables") or [])},
        )
        handler._send_json({"tenant_id": context.tenant_id, "metadata": result})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_acquisition_metadata_status_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_asset_permission(context, "read")
        topic_table_id = first_query_value(params, "topic_table_id") or ""
        if not topic_table_id:
            raise ValueError("topic_table_id_required")
        status = handler.services.topic_metadata_service.status(context.tenant_id, topic_table_id)
        handler._send_json({"tenant_id": context.tenant_id, "metadata": status})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_acquisition_executions_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_asset_permission(context, "read")
        topic_table_id = first_query_value(params, "topic_table_id") or None
        limit = int(first_query_value(params, "limit") or 50)
        executions = handler.services.topic_metadata_service.executions(context.tenant_id, topic_table_id, limit)
        handler._send_json({"tenant_id": context.tenant_id, "executions": executions, "count": len(executions)})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_acquisition_scheduled_task(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_asset_permission(context, "create")
        handler._require_automation_permission(context, "create")
        job_id = str(payload.get("acquisition_job_id") or "").strip()
        topic_table_id = str(payload.get("topic_table_id") or "").strip()
        connection_id = str(payload.get("connection_id") or "").strip()
        keep_latest_n = max(1, min(int(payload.get("keep_latest_n") or 3), 30))
        job = handler.services.data_acquisition_service.validate_scheduled_task(
            context.tenant_id,
            job_id,
            topic_table_id=topic_table_id or None,
            connection_id=connection_id or None,
        )
        definition = payload.get("definition")
        if not isinstance(definition, dict):
            raise ValueError("scheduled_task_definition_required")
        task_config = definition.get("task_config") if isinstance(definition.get("task_config"), dict) else {}
        task = handler.services.automation_runtime.create_task(
            context.tenant_id,
            {
                **definition,
                "task_type": "acquisition",
                "handler_ref": "acquisition.run",
                "task_config": {
                    **task_config,
                    "acquisition_job_id": job_id,
                    "topic_table_id": str(job.get("topic_table_id") or topic_table_id),
                    "connection_id": str(job.get("connection_id") or connection_id),
                    "org_unit_id": str(payload.get("org_unit_id") or "") or None,
                    "keep_latest_n": keep_latest_n,
                },
            },
            context.user_id,
        )
        handler._write_audit(
            context,
            "data_acquisition.scheduled_task.create",
            "automation_task",
            task["automation_task_id"],
            {"acquisition_job_id": job_id, "keep_latest_n": keep_latest_n},
        )
        handler._send_json({"tenant_id": context.tenant_id, "task": task, "job": job})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_latest_acquisition_csv_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_asset_permission(context, "read")
        topic_table_id = first_query_value(params, "topic_table_id") or ""
        org_unit_id = first_query_value(params, "org_id") or first_query_value(params, "org_unit_id")
        include_content = (first_query_value(params, "include_content") or "").lower() in {"1", "true", "yes"}
        artifact = handler.services.data_acquisition_service.latest_csv(
            context.tenant_id,
            topic_table_id,
            org_unit_id,
            include_content=include_content,
        )
        handler._send_json({"tenant_id": context.tenant_id, "artifact": artifact})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_acquisition_artifact_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_asset_permission(context, "read")
        artifact_id = first_query_value(params, "artifact_id") or ""
        if not artifact_id:
            raise ValueError("artifact_id_required")
        artifact, content = handler.services.data_acquisition_service.get_artifact_content(context.tenant_id, artifact_id)
        handler._send_bytes(
            content,
            content_type=str(artifact["content_type"]),
            headers={"Content-Disposition": f'attachment; filename="{artifact_id}.csv"'},
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_acquisition_source_create(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_asset_permission(context, "create")
        source = handler.services.data_acquisition_service.create_source(context.tenant_id, payload, context.user_id)
        handler._write_audit(context, "data_acquisition.source.create", "source_system", source["source_system_id"])
        handler._send_json({"tenant_id": context.tenant_id, "source": source})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_acquisition_script_create(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_asset_permission(context, "create")
        version = handler.services.data_acquisition_service.create_script_version(context.tenant_id, payload, context.user_id)
        handler._write_audit(
            context,
            "data_acquisition.script_version.create",
            "acquisition_script_version",
            version["script_version_id"],
            {"source_hash": version["source_hash"], "runtime": version["runtime"]},
        )
        handler._send_json({"tenant_id": context.tenant_id, "script_version": version})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_acquisition_script_review(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_asset_permission(context, "manage")
        version_id = str(payload.get("script_version_id") or "").strip()
        decision = str(payload.get("decision") or "").strip()
        version = handler.services.data_acquisition_service.review_script_version(
            context.tenant_id,
            version_id,
            decision,
            context.user_id,
        )
        handler._write_audit(
            context,
            "data_acquisition.script_version.review",
            "acquisition_script_version",
            version_id,
            {"decision": decision, "source_hash": version["source_hash"]},
        )
        handler._send_json({"tenant_id": context.tenant_id, "script_version": version})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_acquisition_job_create(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_asset_permission(context, "create")
        job = handler.services.data_acquisition_service.create_job(context.tenant_id, payload, context.user_id)
        handler._write_audit(context, "data_acquisition.job.create", "acquisition_job", job["acquisition_job_id"])
        handler._send_json({"tenant_id": context.tenant_id, "job": job})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_acquisition_run(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_asset_permission(context, "create")
        job_id = str(payload.get("acquisition_job_id") or "").strip()
        org_unit_id = str(payload.get("org_unit_id") or payload.get("org_id") or "").strip() or None
        input_cursor = payload.get("input_cursor", {})
        if not isinstance(input_cursor, dict):
            raise ValueError("input_cursor_must_be_object")
        idempotency_key = str(handler.headers.get("Idempotency-Key") or payload.get("idempotency_key") or f"manual-{uuid4().hex}")
        run = handler.services.data_acquisition_service.run_job(
            context.tenant_id,
            job_id,
            context.user_id,
            idempotency_key,
            org_unit_id=org_unit_id,
            input_cursor=input_cursor,
        )
        handler._write_audit(
            context,
            "data_acquisition.run",
            "acquisition_run",
            run["acquisition_run_id"],
            {"status": run["status"], "job_id": job_id},
        )
        handler._send_json({"tenant_id": context.tenant_id, "run": run})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_acquisition_repair_review(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_asset_permission(context, "manage")
        proposal_id = str(payload.get("repair_proposal_id") or "").strip()
        decision = str(payload.get("decision") or "").strip()
        proposal = handler.services.data_acquisition_service.review_repair_proposal(
            context.tenant_id,
            proposal_id,
            decision,
            context.user_id,
        )
        handler._write_audit(
            context,
            "data_acquisition.repair.review",
            "acquisition_repair_proposal",
            proposal_id,
            {"decision": decision, "applied_script_version_id": proposal.get("applied_script_version_id")},
        )
        handler._send_json({"tenant_id": context.tenant_id, "repair_proposal": proposal})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)
