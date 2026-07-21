from __future__ import annotations

from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import first_query_value, send_route_exception
from backend.platform.application.store import ApplicationActionUnavailable, UnsupportedApplicationAction


def handle_application_module_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        module_key = first_query_value(params, "module_key")
        if not module_key:
            raise ValueError("module_key is required.")
        handler._require_application_permission(context, "read")
        module = handler.services.application_store.get_module(context.tenant_id, module_key, actor_user_id=context.user_id)
        handler._send_json(module)
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_application_action_post(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        module_key = str(payload.get("module_key") or "").strip()
        action = str(payload.get("action") or "").strip()
        action_payload = payload.get("payload")
        if not module_key:
            raise ValueError("module_key is required.")
        if not action:
            raise ValueError("action is required.")
        if action_payload is not None and not isinstance(action_payload, dict):
            raise ValueError("payload must be an object.")
        if module_key == "agent_workspace" and action in {"create_todo", "update_todo", "create_task", "update_task"}:
            action_payload = dict(action_payload or {})
            if action in {"create_todo", "create_task"}:
                action_payload["ownerUserId"] = context.user_id
            if action in {"create_task", "update_task"} and isinstance(action_payload.get("task"), dict):
                task_payload = dict(action_payload["task"])
                if action == "create_task":
                    task_payload["ownerUserId"] = context.user_id
                    task_payload["createdBy"] = context.user_id
                action_payload["task"] = task_payload
        handler._require_application_permission(context, "execute")
        result = handler.services.application_store.run_action(
            context.tenant_id,
            module_key,
            action,
            payload=action_payload or {},
            actor_user_id=context.user_id,
        )
        handler._write_audit(
            context,
            f"application.{action}",
            "application_module",
            target_id=module_key,
            detail={"payload": action_payload or {}, "result": result.get("result", {})},
        )
        handler._send_json(result)
    except UnsupportedApplicationAction as exc:
        handler._send_json(
            {"error": "unsupported_application_action", "message": "The application action is not registered."},
            HTTPStatus.BAD_REQUEST,
        )
    except ApplicationActionUnavailable as exc:
        handler._send_json(
            {"error": "application_action_not_implemented", "message": "The application action has no production handler."},
            HTTPStatus.NOT_IMPLEMENTED,
        )
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)
