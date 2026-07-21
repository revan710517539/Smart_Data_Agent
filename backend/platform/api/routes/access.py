from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import first_query_value, send_route_exception


def handle_access_users_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        execution_context = context.to_execution_context()
        users = handler.services.access_service.list_users(execution_context)
        roles = handler.services.access_service.list_roles(execution_context)
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                "users": users,
                "roles": roles,
                "count": {"users": len(users), "roles": len(roles)},
            }
        )
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_access_user_upsert(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        user = payload.get("user")
        if not isinstance(user, dict):
            raise ValueError("user must be an object.")
        saved = handler.services.access_service.upsert_user(context.to_execution_context(), user)
        revoked_sessions = handler.services.session_store.revoke_user(
            str(saved.get("id") or ""),
            reason="account_or_role_updated",
        )
        handler._write_audit(context, "access.user.upsert", "user", str(saved.get("id") or ""))
        handler._send_json({"tenant_id": context.tenant_id, "user": saved, "revoked_sessions": revoked_sessions})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_access_user_delete(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        user_id = first_query_value(params, "target_user_id") or first_query_value(params, "user_id")
        if not user_id:
            raise ValueError("user_id is required.")
        deleted = handler.services.access_service.delete_user(context.to_execution_context(), user_id)
        revoked_sessions = handler.services.session_store.revoke_user(user_id, reason="account_deleted")
        handler._write_audit(context, "access.user.delete", "user", user_id, {"deleted": deleted})
        handler._send_json({"tenant_id": context.tenant_id, "user_id": user_id, "deleted": deleted, "revoked_sessions": revoked_sessions})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_access_role_policies_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        permissions = handler.services.access_service.list_role_permissions(context.to_execution_context())
        handler._send_json({"tenant_id": context.tenant_id, "permissions": permissions, "count": len(permissions)})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_access_role_policy_save(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        permission = payload.get("permission")
        if not isinstance(permission, dict):
            raise ValueError("permission must be an object.")
        saved = handler.services.access_service.save_role_permission(context.to_execution_context(), permission)
        handler._write_audit(context, "access.role_policy.save", "role_policy", str(saved.get("id") or ""))
        handler._send_json({"tenant_id": context.tenant_id, "permission": saved})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)
