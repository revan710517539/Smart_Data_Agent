from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import first_query_value, send_route_exception
from backend.platform.tenancy.catalog import catalog_tenant_ids


def handle_tenant_governance_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        _require_super_admin(handler, context)
        tenant_id = str(first_query_value(params, "tenant_id") or context.tenant_id).strip()
        _require_active_tenant(handler, tenant_id)
        handler._send_json(handler.services.tenant_scope_service.snapshot(tenant_id))
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_tenant_governance_create(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        _require_super_admin(handler, context)
        kind = str(payload.get("kind") or "").strip()
        active_tenants = set(catalog_tenant_ids(handler.services))
        if kind == "topic_assignment":
            saved = handler.services.tenant_scope_service.assign_topic(
                actor_user_id=context.user_id,
                tenant_id=str(payload.get("tenant_id") or payload.get("tenantId") or "").strip(),
                topic_skill_id=str(payload.get("topic_skill_id") or payload.get("topicSkillId") or "").strip(),
                active_tenant_ids=active_tenants,
                expires_at=str(payload.get("expires_at") or payload.get("expiresAt") or "").strip(),
            )
            handler._write_audit(
                context,
                "tenancy.topic.assign",
                "tenant_topic_assignment",
                saved["assignment_id"],
                {"tenant_id": saved["tenant_id"], "topic_skill_id": saved["topic_skill_id"]},
            )
            handler._send_json({"kind": kind, "assignment": saved}, 201)
            return
        if kind == "resource_grant":
            saved = handler.services.tenant_scope_service.create_resource_grant(
                actor_user_id=context.user_id,
                source_tenant_id=str(payload.get("source_tenant_id") or payload.get("sourceTenantId") or "").strip(),
                recipient_tenant_id=str(payload.get("recipient_tenant_id") or payload.get("recipientTenantId") or "").strip(),
                resource_type=str(payload.get("resource_type") or payload.get("resourceType") or "").strip(),
                resource_key=str(payload.get("resource_key") or payload.get("resourceKey") or "").strip(),
                actions=list(payload.get("actions") or []),
                field_scope=list(payload.get("field_scope") or payload.get("fieldScope") or []),
                schema_fingerprint=str(payload.get("schema_fingerprint") or payload.get("schemaFingerprint") or "").strip(),
                purpose=str(payload.get("purpose") or "").strip(),
                active_tenant_ids=active_tenants,
                effective_at=str(payload.get("effective_at") or payload.get("effectiveAt") or "").strip(),
                expires_at=str(payload.get("expires_at") or payload.get("expiresAt") or "").strip(),
            )
            handler._write_audit(
                context,
                "tenancy.resource_grant.create",
                "cross_tenant_resource_grant",
                saved["grant_id"],
                {
                    "source_tenant_id": saved["source_tenant_id"],
                    "recipient_tenant_id": saved["recipient_tenant_id"],
                    "resource_type": saved["resource_type"],
                    "resource_key": saved["resource_key"],
                    "expires_at": saved["expires_at"],
                },
            )
            handler._send_json({"kind": kind, "grant": saved}, 201)
            return
        raise ValueError("tenant_governance_kind_invalid")
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_tenant_governance_delete(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        _require_super_admin(handler, context)
        kind = str(first_query_value(params, "kind") or "").strip()
        reason = str(first_query_value(params, "reason") or "").strip()
        if kind == "topic_assignment":
            saved = handler.services.tenant_scope_service.revoke_topic(
                str(first_query_value(params, "assignment_id") or "").strip(),
                context.user_id,
                reason,
            )
            handler._write_audit(
                context,
                "tenancy.topic.revoke",
                "tenant_topic_assignment",
                saved["assignment_id"],
                {"tenant_id": saved["tenant_id"], "reason": reason},
            )
            handler._send_json({"kind": kind, "assignment": saved, "revoked": True})
            return
        if kind == "resource_grant":
            saved = handler.services.tenant_scope_service.revoke_resource_grant(
                str(first_query_value(params, "grant_id") or "").strip(),
                context.user_id,
                reason,
            )
            handler._write_audit(
                context,
                "tenancy.resource_grant.revoke",
                "cross_tenant_resource_grant",
                saved["grant_id"],
                {"source_tenant_id": saved["source_tenant_id"], "recipient_tenant_id": saved["recipient_tenant_id"], "reason": reason},
            )
            handler._send_json({"kind": kind, "grant": saved, "revoked": True})
            return
        raise ValueError("tenant_governance_kind_invalid")
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def _require_super_admin(handler: Any, context: Any) -> None:
    checker = getattr(handler.services.access_service, "_is_super_admin", None)
    if not callable(checker) or not checker(context.user_id):
        raise PermissionError("tenant_governance_super_admin_required")


def _require_active_tenant(handler: Any, tenant_id: str) -> None:
    if tenant_id not in set(catalog_tenant_ids(handler.services)):
        raise ValueError("tenant_governance_tenant_not_active")
