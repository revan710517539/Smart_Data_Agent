from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import send_route_exception
from backend.platform.navigation import flatten_navigation_keys, serialize_navigation, visible_navigation_tree


def handle_navigation_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        tree = visible_navigation_tree(handler.services.permission_broker, context.to_execution_context())
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                "user_id": context.user_id,
                "menu_keys": flatten_navigation_keys(tree),
                "menu_tree": serialize_navigation(tree),
            }
        )
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)
