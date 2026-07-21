from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import send_route_exception


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
        snapshot = handler.services.operating_snapshot_service.build(
            view, context.tenant_id, context.user_id, filters
        )
        handler._send_json({"tenant_id": context.tenant_id, **snapshot})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)
