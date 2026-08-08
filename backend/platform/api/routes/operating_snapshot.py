from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.authz import normalize_tenant_id
from backend.authz.seed import OPERATING_TENANTS
from backend.platform.api.support import send_route_exception
from backend.platform.tenancy import ExecutionContext


def handle_operating_snapshot_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_application_permission(context, "read")
        view = str((params.get("view") or [""])[0]).strip()
        filters = {
            key: values[0]
            for key, values in params.items()
            if key != "view" and values
        }
        if view == "dashboard":
            snapshot = handler.services.operating_snapshot_service.build_authorized_dashboard(
                _authorized_dashboard_tenant_ids(handler, context),
                context.user_id,
                filters,
            )
        else:
            snapshot = handler.services.operating_snapshot_service.build(
                view, context.tenant_id, context.user_id, filters
            )
        handler._send_json({"tenant_id": context.tenant_id, **snapshot})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def _authorized_dashboard_tenant_ids(handler: Any, context: Any) -> tuple[str, ...]:
    """Return only institutions where this user may read the dashboard."""
    repository = handler.services.permission_broker.enforcer.repository
    candidates: set[str] = {str(context.tenant_id)}
    for assignment in repository.list_user_assignments(context.user_id):
        tenant_id = str(assignment.tenant_id or "").strip()
        if tenant_id == "*":
            candidates.update(normalize_tenant_id(name) for name in OPERATING_TENANTS)
        elif tenant_id:
            candidates.add(tenant_id)
    approved: list[str] = []
    for tenant_id in sorted(candidates):
        try:
            handler.services.permission_broker.require_resource(
                ExecutionContext(user_id=context.user_id, tenant_id=tenant_id),
                "application:*",
                "read",
            )
        except PermissionError:
            continue
        approved.append(tenant_id)
    if not approved:
        raise PermissionError("dashboard_tenant_scope_empty")
    return tuple(approved)
