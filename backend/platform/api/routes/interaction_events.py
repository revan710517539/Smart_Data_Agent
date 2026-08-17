from __future__ import annotations

from http.cookies import SimpleCookie
from typing import Any

from backend.platform.api.support import send_route_exception
from backend.platform.security import AuthenticationError


def handle_interaction_event_create(handler: Any) -> None:
    try:
        _require_explicit_session(handler)
        payload = handler._read_json(max_bytes=16 * 1024)
        context = handler._request_context(payload=payload)
        profile = handler.services.access_service.user_store.get_profile(context.user_id)
        event = handler.services.interaction_event_store.write(
            tenant_id=context.tenant_id,
            actor_user_id=context.user_id,
            actor_account=str(getattr(profile, "email", "") or getattr(profile, "name", "") or context.user_id),
            event_name=str(payload.get("event_name") or ""),
            event_type=str(payload.get("event_type") or "click"),
            page_path=str(payload.get("page_path") or ""),
            page_name=str(payload.get("page_name") or ""),
            chart_id=str(payload.get("chart_id") or ""),
            chart_name=str(payload.get("chart_name") or ""),
            resource_type=str(payload.get("resource_type") or ""),
            resource_id=str(payload.get("resource_id") or ""),
            extension=payload.get("extension") if isinstance(payload.get("extension"), dict) else {},
        )
        handler._send_json({"status": "recorded", "event_id": event["event_id"]})
    except Exception as exc:
        send_route_exception(handler, exc)


def _require_explicit_session(handler: Any) -> None:
    cookie = SimpleCookie()
    cookie.load(str(handler.headers.get("Cookie") or ""))
    authorization = str(handler.headers.get("Authorization") or "").strip()
    if "sda_session" not in cookie and not authorization.lower().startswith("bearer "):
        raise AuthenticationError("interaction_event_login_required")
