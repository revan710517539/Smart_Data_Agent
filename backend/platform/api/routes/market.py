from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import send_route_exception


def handle_market_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_market_permission(context, "read")
        bundle = handler.services.market_service.bundle(context.tenant_id)
        handler._send_json(
            {"tenant_id": context.tenant_id, **bundle, "count": {key: len(value) for key, value in bundle.items()}}
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def _create(handler: Any, kind: str) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_market_permission(context, "create")
        creator = {
            "source": handler.services.market_service.create_source,
            "entity": handler.services.market_service.create_entity,
            "observation": handler.services.market_service.create_observation,
            "rule": handler.services.market_service.create_rule,
        }[kind]
        result = creator(context.tenant_id, payload, context.user_id)
        identifier = str(
            result.get("market_source_id")
            or result.get("market_entity_id")
            or result.get("market_observation_id")
            or result.get("market_rule_id")
            or ""
        )
        handler._write_audit(context, f"market.{kind}.create", f"market_{kind}", identifier)
        handler._send_json({"tenant_id": context.tenant_id, kind: result})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_market_source_create(handler: Any) -> None:
    _create(handler, "source")


def handle_market_entity_create(handler: Any) -> None:
    _create(handler, "entity")


def handle_market_observation_create(handler: Any) -> None:
    _create(handler, "observation")


def handle_market_rule_create(handler: Any) -> None:
    _create(handler, "rule")


def handle_market_evaluate(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_market_permission(context, "manage")
        rule_id = str(payload.get("market_rule_id") or "").strip() or None
        result = handler.services.market_service.evaluate(context.tenant_id, rule_id)
        handler._write_audit(
            context,
            "market.rules.evaluate",
            "market_rule",
            rule_id or "all",
            {"evaluated_observations": result["evaluated_observations"], "created_count": result["created_count"]},
        )
        handler._send_json({"tenant_id": context.tenant_id, **result})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_market_event_status(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_market_permission(context, "manage")
        event_id = str(payload.get("market_event_id") or "").strip()
        status = str(payload.get("status") or "").strip()
        event = handler.services.market_store.update_event_status(
            context.tenant_id, event_id, status, context.user_id
        )
        handler._write_audit(
            context, "market.event.status", "market_event", event_id, {"status": event["status"]}
        )
        handler._send_json({"tenant_id": context.tenant_id, "event": event})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)
