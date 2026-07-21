from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import first_query_value, send_route_exception


def handle_memory_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_memory_permission(context, "read")
        view = (first_query_value(params, "view") or "active").strip().lower()
        if view == "candidates":
            handler._require_memory_permission(context, "manage")
            records = handler.services.memory_service.list_candidates(context.tenant_id)
        else:
            records = handler.services.memory_service.list_active(context.tenant_id, context.user_id)
        handler._send_json({"tenant_id": context.tenant_id, "view": view, "records": records, "count": len(records)})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_memory_candidate_create(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_memory_permission(context, "create")
        record = handler.services.memory_service.create_candidate(context.tenant_id, payload, context.user_id)
        handler._write_audit(
            context,
            "memory.candidate.create",
            "memory_record",
            record["memory_id"],
            {"memory_type": record["memory_type"], "status": record["status"], "content_hash": record["content_hash"]},
        )
        handler._send_json({"tenant_id": context.tenant_id, "record": record})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_memory_candidate_review(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_memory_permission(context, "manage")
        memory_id = str(payload.get("memory_id") or "").strip()
        decision = str(payload.get("decision") or "").strip()
        record = handler.services.memory_service.review_candidate(
            context.tenant_id,
            memory_id,
            decision,
            context.user_id,
            str(payload.get("comments") or ""),
        )
        handler._write_audit(
            context,
            "memory.candidate.review",
            "memory_record",
            memory_id,
            {"decision": decision, "status": record["status"], "content_hash": record["content_hash"]},
        )
        handler._send_json({"tenant_id": context.tenant_id, "record": record})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)
