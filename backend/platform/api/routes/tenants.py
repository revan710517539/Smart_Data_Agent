from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import first_query_value, send_route_exception
from backend.platform.tenancy.catalog import (
    create_tenant,
    delete_tenant,
    list_active_tenants,
    update_tenant,
)


def handle_tenants_get(handler: Any, query: str) -> None:
    try:
        tenants = _active_tenants(handler)
        handler._send_json({"tenants": tenants, "count": len(tenants)})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_tenants_create(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        _require_super_admin(handler, context)
        tenant = create_tenant(
            handler.services,
            str(payload.get("name") or payload.get("tenant") or ""),
            actor_user_id=context.user_id,
        )
        handler._write_audit(context, "tenancy.tenant.create", "tenant", tenant["id"], {"name": tenant["name"]})
        handler._send_json({"tenant": tenant, "tenants": list_active_tenants(handler.services)})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_tenants_update(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        _require_super_admin(handler, context)
        tenant = update_tenant(
            handler.services,
            str(payload.get("id") or payload.get("tenant_id") or ""),
            str(payload.get("name") or payload.get("tenant") or ""),
        )
        handler._write_audit(context, "tenancy.tenant.update", "tenant", tenant["id"], {"name": tenant["name"]})
        handler._send_json({"tenant": tenant, "tenants": list_active_tenants(handler.services)})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_tenants_delete(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        _require_super_admin(handler, context)
        tenant_id = first_query_value(params, "tenant_id") or first_query_value(params, "id") or ""
        tenant = delete_tenant(handler.services, tenant_id, actor_user_id=context.user_id)
        handler._write_audit(context, "tenancy.tenant.delete", "tenant", tenant["id"], {"name": tenant["name"]})
        handler._send_json({"tenant": tenant, "deleted": True, "tenants": list_active_tenants(handler.services)})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def _active_tenants(handler: Any) -> list[dict[str, str]]:
    """Return the active login catalog from the runtime's tenant authority.

    Local SQLite development has no relational tenant catalog and keeps the
    source-controlled operating list until a super administrator writes the
    durable overlay. Relational deployments must expose only actually
    provisioned tenants; otherwise the login page can offer a tenant that the
    same database will reject during session creation.
    """

    return list_active_tenants(handler.services)


def _require_super_admin(handler: Any, context: Any) -> None:
    access_service = getattr(handler.services, "access_service", None)
    checker = getattr(access_service, "_is_super_admin", None)
    if not callable(checker) or not checker(context.user_id):
        raise PermissionError("tenant_catalog_super_admin_required")
