from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
        limit = _bounded_page_limit(first_query_value(params, "limit"))
        offset = _bounded_offset(first_query_value(params, "offset"))
        since = _audit_since(first_query_value(params, "since"))
        tenant_ids = _authorized_audit_tenant_ids(handler, context)
        list_for_tenants = getattr(handler.services.audit_store, "list_for_tenants", None)
        count_for_tenants = getattr(handler.services.audit_store, "count_for_tenants", None)
        if callable(list_for_tenants):
            logs = list_for_tenants(list(tenant_ids), limit=limit, offset=offset, since=since)
        else:
            all_logs = [
                item
                for tenant_id in tenant_ids
                for item in handler.services.audit_store.list(tenant_id, limit=limit + offset, since=since)
            ]
            logs = all_logs[offset: offset + limit]
        logs = [_with_actor_name(handler, item) for item in logs]
        if callable(count_for_tenants):
            total = count_for_tenants(list(tenant_ids), since=since)
        else:
            total = offset + len(logs)
        handler._send_json({
            "tenant_id": context.tenant_id,
            "tenant_ids": list(tenant_ids),
            "logs": logs,
            "count": len(logs),
            "total": total,
            "limit": limit,
            "offset": offset,
            "since": since,
        })
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def _with_actor_name(handler: Any, item: dict[str, Any]) -> dict[str, Any]:
    actor_user_id = str(item.get("actor_user_id") or "").strip()
    actor_name = ""
    try:
        profile = handler.services.access_service.user_store.get_profile(actor_user_id) if actor_user_id else None
        actor_name = str(getattr(profile, "name", "") or "").strip()
    except Exception:
        actor_name = ""
    return {**item, "actor_name": actor_name or "未知用户"}


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


def _audit_since(value: str | None) -> str:
    raw = str(value or "").strip()
    if raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        else:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
    return (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()


def _bounded_page_limit(value: str | None) -> int:
    return max(1, min(int(value or "20"), 100))


def _bounded_offset(value: str | None) -> int:
    return max(0, min(int(value or "0"), 100_000))
