from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import first_query_value, send_route_exception


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
        logs = handler.services.audit_store.list(context.tenant_id, limit=limit)
        handler._send_json({"tenant_id": context.tenant_id, "logs": logs, "count": len(logs)})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)
