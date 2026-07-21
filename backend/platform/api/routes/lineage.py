from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import first_query_value, send_route_exception


def handle_lineage_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_asset_permission(context, "read")
        entity_type = first_query_value(params, "entity_type") or ""
        entity_id = first_query_value(params, "entity_id") or ""
        direction = first_query_value(params, "direction") or "both"
        max_depth = int(first_query_value(params, "max_depth") or 4)
        graph = handler.services.lineage_store.graph(
            context.tenant_id,
            entity_type,
            entity_id,
            direction=direction,
            max_depth=max_depth,
        )
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                **graph,
                "count": {"nodes": len(graph["nodes"]), "edges": len(graph["edges"])},
            }
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)
