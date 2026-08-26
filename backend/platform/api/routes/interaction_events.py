from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import first_query_value, send_route_exception
from backend.platform.interaction_events import build_interaction_analytics
from backend.platform.security import AuthenticationError


def handle_interaction_analytics_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        _require_interaction_analytics_admin(handler, context)
        days = _bounded_days(first_query_value(params, "days"))
        page = _bounded_page(first_query_value(params, "page"))
        page_size = _bounded_page_size(first_query_value(params, "page_size"))
        actor_user_id = str(first_query_value(params, "actor_user_id") or "").strip()[:200]
        until = datetime.now(timezone.utc)
        since = until - timedelta(days=days)
        store = handler.services.interaction_event_store
        list_range = getattr(store, "list_global_range", None)
        count_range = getattr(store, "count_global_range", None)
        if not callable(list_range) or not callable(count_range):
            raise RuntimeError("interaction_analytics_store_unavailable")
        events = list_range(
            since=since.isoformat(),
            until=until.isoformat(),
            limit=20_000,
            offset=0,
        )
        total = count_range(since=since.isoformat(), until=until.isoformat())
        snapshot = build_interaction_analytics(
            events,
            since=since.isoformat(),
            until=until.isoformat(),
            total_count=total,
            timeline_actor_user_id=actor_user_id,
            timeline_page=page,
            timeline_page_size=page_size,
        )
        handler._send_json({"tenant_id": context.tenant_id, "scope": "global", **snapshot})
    except Exception as exc:
        send_route_exception(handler, exc)


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


def _require_interaction_analytics_admin(handler: Any, context: Any) -> None:
    if not handler.services.permission_broker.enforcer.has_super_admin_role(context.user_id, context.tenant_id):
        raise PermissionError("global_super_admin_required")


def _bounded_days(value: str | None) -> int:
    return max(1, min(int(value or "7"), 90))


def _bounded_page(value: str | None) -> int:
    return max(1, min(int(value or "1"), 2_000))


def _bounded_page_size(value: str | None) -> int:
    return max(1, min(int(value or "50"), 100))
