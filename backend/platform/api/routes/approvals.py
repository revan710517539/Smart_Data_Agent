from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import send_route_exception


def handle_capability_approvals_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler.services.permission_broker.require_resource(
            context.to_execution_context(), "approval:*", "manage"
        )
        status = str((params.get("status") or [""])[0]).strip() or None
        items = handler.services.approval_store.list(context.tenant_id, status=status)
        handler._send_json({"tenant_id": context.tenant_id, "approvals": items, "count": len(items)})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_capability_approval_request(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        subject_type = str(payload.get("subject_type") or "").strip()
        subject_id = str(payload.get("subject_id") or "").strip()
        action = str(payload.get("action") or "execute").strip()
        input_hash = str(payload.get("input_hash") or "").strip().lower()
        if subject_type == "skill":
            handler.services.permission_broker.require_resource(
                context.to_execution_context(), f"skill:{subject_id}", action
            )
        elif subject_type == "mcp":
            handler.services.permission_broker.require_resource(
                context.to_execution_context(), f"mcp:{subject_id}", action
            )
        else:
            raise ValueError("invalid_capability_approval_subject_type")
        item = handler.services.approval_store.request(
            context.tenant_id,
            subject_type,
            subject_id,
            action,
            input_hash,
            context.user_id,
            reason=str(payload.get("reason") or ""),
        )
        handler._write_audit(
            context,
            "capability.approval.request",
            subject_type,
            item["approval_id"],
            {"subject_id": subject_id, "action": action, "input_hash": input_hash},
        )
        handler._send_json({"tenant_id": context.tenant_id, "approval": item})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_capability_approval_review(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler.services.permission_broker.require_resource(
            context.to_execution_context(), "approval:*", "manage"
        )
        approval_id = str(payload.get("approval_id") or "").strip()
        if not approval_id:
            raise ValueError("approval_id is required")
        item = handler.services.approval_store.review(
            context.tenant_id,
            approval_id,
            context.user_id,
            str(payload.get("decision") or "").strip(),
            ttl_seconds=int(payload.get("ttl_seconds") or 900),
            comments=str(payload.get("comments") or ""),
        )
        handler._write_audit(
            context,
            "capability.approval.review",
            item["subject_type"],
            approval_id,
            {"decision": item["status"], "subject_id": item["subject_id"]},
        )
        handler._send_json({"tenant_id": context.tenant_id, "approval": item})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)
