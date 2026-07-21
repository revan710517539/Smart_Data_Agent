from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import first_query_value, send_route_exception


def handle_trace_spans_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_system_config_permission(context, "read")
        trace_id = first_query_value(params, "trace_id") or ""
        if not trace_id:
            raise ValueError("trace_id_required")
        owns_trace = getattr(handler.services.task_repository, "trace_belongs_to_tenant", None)
        if not callable(owns_trace) or not owns_trace(context.tenant_id, trace_id):
            raise KeyError("trace_not_found")
        read_spans = getattr(handler.services.task_repository, "trace_spans", None)
        spans = read_spans(trace_id) if callable(read_spans) else []
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                "trace_id": trace_id,
                "spans": spans,
                "count": len(spans),
            }
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)
