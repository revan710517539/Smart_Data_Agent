from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from threading import RLock
from typing import Any
from uuid import uuid4

from backend.platform.database.identity import PostgreSQLIdentityResolver


_SECRET_PARTS = ("password", "secret", "token", "authorization", "cookie", "credential", "sql", "rows", "raw_data")
_TEXT_KEYS = {"question", "reply", "input", "answer"}


def sanitize_interaction_extension(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if depth > 3:
        return "[depth_limited]"
    normalized_key = key.lower().replace("-", "_")
    if any(part in normalized_key for part in _SECRET_PARTS):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(item_key)[:80]: sanitize_interaction_extension(item_value, key=str(item_key), depth=depth + 1) for item_key, item_value in list(value.items())[:30]}
    if isinstance(value, list):
        return [sanitize_interaction_extension(item, key=key, depth=depth + 1) for item in value[:20]]
    if isinstance(value, str):
        text = re.sub(r"(?i)(password|token|secret|authorization|cookie)\s*[:=]\s*\S+", r"\1=[redacted]", value)
        return text[:500] if normalized_key in _TEXT_KEYS else text[:240]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:240]


def normalize_interaction_event(
    *,
    tenant_id: str,
    actor_user_id: str,
    actor_account: str,
    event_name: str,
    event_type: str,
    page_path: str = "",
    page_name: str = "",
    chart_id: str = "",
    chart_name: str = "",
    resource_type: str = "",
    resource_id: str = "",
    extension: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_type = event_type.strip().lower()
    if normalized_type not in {"click", "view"}:
        raise ValueError("interaction_event_type_invalid")
    normalized_name = event_name.strip()
    if not normalized_name or len(normalized_name) > 120:
        raise ValueError("interaction_event_name_invalid")
    return {
        "event_id": str(uuid4()),
        "tenant_id": tenant_id,
        "actor_user_id": actor_user_id,
        "actor_account": actor_account.strip()[:320],
        "event_name": normalized_name,
        "event_type": normalized_type,
        "page_path": page_path.strip()[:500],
        "page_name": page_name.strip()[:200],
        "chart_id": chart_id.strip()[:200],
        "chart_name": chart_name.strip()[:300],
        "resource_type": resource_type.strip()[:120],
        "resource_id": resource_id.strip()[:200],
        "extension": sanitize_interaction_extension(extension or {}),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }


class InMemoryInteractionEventStore:
    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []
        self._lock = RLock()

    def write(self, **values: Any) -> dict[str, Any]:
        event = normalize_interaction_event(**values)
        with self._lock:
            self._items.append(event)
        return dict(event)

    def list(self, tenant_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in reversed(self._items) if item["tenant_id"] == tenant_id][:_bounded_limit(limit)]


class MySQLInteractionEventStore:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    def write(self, **values: Any) -> dict[str, Any]:
        event = normalize_interaction_event(**values)
        with self.pool.transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, event["tenant_id"])
            actor_key = PostgreSQLIdentityResolver.user_id(connection, event["actor_user_id"], required=False)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_user_interaction_events(
                      interaction_event_id, tenant_id, actor_user_id, actor_account,
                      event_name, event_type, page_path, page_name, chart_id, chart_name,
                      resource_type, resource_id, extension, occurred_at, created_by
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        event["event_id"], tenant_key, actor_key, event["actor_account"],
                        event["event_name"], event["event_type"], event["page_path"], event["page_name"],
                        event["chart_id"] or None, event["chart_name"] or None,
                        event["resource_type"] or None, event["resource_id"] or None,
                        json.dumps(event["extension"], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                        event["occurred_at"], actor_key,
                    ),
                )
        return event


def _bounded_limit(value: int) -> int:
    return max(1, min(int(value or 100), 500))
