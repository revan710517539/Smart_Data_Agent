from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.authz import normalize_tenant_id
from backend.authz.seed import OPERATING_TENANTS
from backend.platform.api.support import first_query_value, send_route_exception
from backend.platform.tenancy import ExecutionContext


def handle_audit_logs_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler.services.permission_broker.require_resource(
            context.to_execution_context(),
            "menu:settings.audit",
            "read",
        )
        limit = int(first_query_value(params, "limit") or "50")
        tenant_ids = _authorized_audit_tenant_ids(handler, context)
        list_for_tenants = getattr(handler.services.audit_store, "list_for_tenants", None)
        if callable(list_for_tenants):
            logs = list_for_tenants(list(tenant_ids), limit=limit)
        else:
            logs = [
                item
                for tenant_id in tenant_ids
                for item in handler.services.audit_store.list(tenant_id, limit=limit)
            ][:limit]
        handler._send_json({"tenant_id": context.tenant_id, "tenant_ids": list(tenant_ids), "logs": logs, "count": len(logs)})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def _authorized_audit_tenant_ids(handler: Any, context: Any) -> tuple[str, ...]:
    repository = handler.services.permission_broker.enforcer.repository
    candidates: set[str] = {str(context.tenant_id)}
    for assignment in repository.list_user_assignments(context.user_id):
        tenant_id = str(assignment.tenant_id or "").strip()
        if tenant_id == "*":
            candidates.update(normalize_tenant_id(name) for name in OPERATING_TENANTS)
        elif tenant_id:
            candidates.add(tenant_id)
    allowed: list[str] = []
    for tenant_id in sorted(candidates):
        try:
            handler.services.permission_broker.require_resource(
                ExecutionContext(user_id=context.user_id, tenant_id=tenant_id),
                "menu:settings.audit",
                "read",
            )
        except PermissionError:
            continue
        allowed.append(tenant_id)
    return tuple(allowed)
