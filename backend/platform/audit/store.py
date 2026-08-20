from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from backend.platform.storage import connect_sqlite
from typing import Any, Protocol
from uuid import uuid4


class AuditEventStore(Protocol):
    def write(
        self,
        tenant_id: str,
        actor_user_id: str,
        action: str,
        target_type: str,
        target_id: str = "",
        detail: dict[str, Any] | None = None,
        ip_address: str = "",
    ) -> dict[str, Any]:
        ...

    def list(self, tenant_id: str, limit: int = 50, offset: int = 0, since: str | None = None) -> list[dict[str, Any]]:
        ...

    def count(self, tenant_id: str, since: str | None = None) -> int:
        ...

    def list_for_tenants(self, tenant_ids: list[str], limit: int = 50, offset: int = 0, since: str | None = None) -> list[dict[str, Any]]:
        ...

    def count_for_tenants(self, tenant_ids: list[str], since: str | None = None) -> int:
        ...


class InMemoryAuditEventStore:
    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    def write(
        self,
        tenant_id: str,
        actor_user_id: str,
        action: str,
        target_type: str,
        target_id: str = "",
        detail: dict[str, Any] | None = None,
        ip_address: str = "",
    ) -> dict[str, Any]:
        event = _normalize_event(tenant_id, actor_user_id, action, target_type, target_id, detail, ip_address)
        self._events.append(event)
        return dict(event)

    def list(self, tenant_id: str, limit: int = 50, offset: int = 0, since: str | None = None) -> list[dict[str, Any]]:
        events = [
            dict(event)
            for event in reversed(self._events)
            if event["tenant_id"] in (tenant_id, "*") and _matches_since(event.get("created_at"), since)
        ]
        return events[_bounded_offset(offset): _bounded_offset(offset) + _bounded_limit(limit)]

    def count(self, tenant_id: str, since: str | None = None) -> int:
        return sum(1 for event in self._events if event["tenant_id"] in (tenant_id, "*") and _matches_since(event.get("created_at"), since))

    def list_for_tenants(self, tenant_ids: list[str], limit: int = 50, offset: int = 0, since: str | None = None) -> list[dict[str, Any]]:
        allowed = set(tenant_ids)
        events = [
            dict(event)
            for event in reversed(self._events)
            if (event["tenant_id"] in allowed or event["tenant_id"] == "*") and _matches_since(event.get("created_at"), since)
        ]
        return events[_bounded_offset(offset): _bounded_offset(offset) + _bounded_limit(limit)]

    def count_for_tenants(self, tenant_ids: list[str], since: str | None = None) -> int:
        allowed = set(tenant_ids)
        return sum(1 for event in self._events if (event["tenant_id"] in allowed or event["tenant_id"] == "*") and _matches_since(event.get("created_at"), since))


class SQLiteAuditEventStore:
    def __init__(self, db_path: str | Path, initialize: bool = True) -> None:
        self.db_path = str(db_path)
        self._conn = connect_sqlite(self.db_path)
        self._conn.row_factory = sqlite3.Row
        if initialize:
            self.init_schema()

    def close(self) -> None:
        self._conn.close()

    def init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS platform_audit_events (
                event_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                actor_user_id TEXT NOT NULL,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '{}',
                ip_address TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_platform_audit_events_tenant_created
                ON platform_audit_events(tenant_id, created_at);
            """
        )
        self._conn.commit()

    def write(
        self,
        tenant_id: str,
        actor_user_id: str,
        action: str,
        target_type: str,
        target_id: str = "",
        detail: dict[str, Any] | None = None,
        ip_address: str = "",
    ) -> dict[str, Any]:
        event = _normalize_event(tenant_id, actor_user_id, action, target_type, target_id, detail, ip_address)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_audit_events(
                    event_id, tenant_id, actor_user_id, action, target_type,
                    target_id, detail, ip_address, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    event["tenant_id"],
                    event["actor_user_id"],
                    event["action"],
                    event["target_type"],
                    event["target_id"],
                    json.dumps(event["detail"], ensure_ascii=False, sort_keys=True),
                    event["ip_address"],
                    event["created_at"],
                ),
            )
        return event

    def list(self, tenant_id: str, limit: int = 50, offset: int = 0, since: str | None = None) -> list[dict[str, Any]]:
        bounded_limit = _bounded_limit(limit)
        bounded_offset = _bounded_offset(offset)
        since_sql, since_params = _since_clause(since, "created_at", "?")
        rows = self._conn.execute(
            f"""
            SELECT event_id, tenant_id, actor_user_id, action, target_type, target_id,
                   detail, ip_address, created_at
            FROM platform_audit_events
            WHERE tenant_id IN (?, '*'){since_sql}
            ORDER BY created_at DESC, event_id DESC
            LIMIT ? OFFSET ?
            """,
            (tenant_id, *since_params, bounded_limit, bounded_offset),
        ).fetchall()
        return [_sqlite_row_to_event(row) for row in rows]

    def count(self, tenant_id: str, since: str | None = None) -> int:
        since_sql, since_params = _since_clause(since, "created_at", "?")
        row = self._conn.execute(
            f"SELECT COUNT(*) AS count FROM platform_audit_events WHERE tenant_id IN (?, '*'){since_sql}",
            (tenant_id, *since_params),
        ).fetchone()
        return int(row["count"] if row is not None else 0)

    def list_for_tenants(self, tenant_ids: list[str], limit: int = 50, offset: int = 0, since: str | None = None) -> list[dict[str, Any]]:
        allowed = sorted({str(item).strip() for item in tenant_ids if str(item).strip()})
        if not allowed:
            return []
        bounded_limit = _bounded_limit(limit)
        bounded_offset = _bounded_offset(offset)
        placeholders = ", ".join("?" for _ in allowed)
        since_sql, since_params = _since_clause(since, "created_at", "?")
        rows = self._conn.execute(
            f"""
            SELECT event_id, tenant_id, actor_user_id, action, target_type, target_id,
                   detail, ip_address, created_at
            FROM platform_audit_events
            WHERE (tenant_id IN ({placeholders}) OR tenant_id = '*'){since_sql}
            ORDER BY created_at DESC, event_id DESC
            LIMIT ? OFFSET ?
            """,
            (*allowed, *since_params, bounded_limit, bounded_offset),
        ).fetchall()
        return [_sqlite_row_to_event(row) for row in rows]

    def count_for_tenants(self, tenant_ids: list[str], since: str | None = None) -> int:
        allowed = sorted({str(item).strip() for item in tenant_ids if str(item).strip()})
        if not allowed:
            return 0
        placeholders = ", ".join("?" for _ in allowed)
        since_sql, since_params = _since_clause(since, "created_at", "?")
        row = self._conn.execute(
            f"SELECT COUNT(*) AS count FROM platform_audit_events WHERE (tenant_id IN ({placeholders}) OR tenant_id = '*'){since_sql}",
            (*allowed, *since_params),
        ).fetchone()
        return int(row["count"] if row is not None else 0)


def _matches_since(created_at: Any, since: str | None) -> bool:
    if not since:
        return True
    return str(created_at or "") >= since


def _since_clause(since: str | None, column: str, placeholder: str) -> tuple[str, tuple[str, ...]]:
    if not since:
        return "", ()
    return f" AND {column} >= {placeholder}", (since,)


def _bounded_limit(limit: int) -> int:
    return max(1, min(int(limit or 50), 200))


def _bounded_offset(offset: int) -> int:
    return max(0, int(offset or 0))


def _sqlite_row_to_event(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "event_id": row["event_id"],
        "tenant_id": row["tenant_id"],
        "actor_user_id": row["actor_user_id"],
        "action": row["action"],
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "detail": json.loads(row["detail"] or "{}"),
        "ip_address": row["ip_address"],
        "created_at": row["created_at"],
    }


def _normalize_event(
    tenant_id: str,
    actor_user_id: str,
    action: str,
    target_type: str,
    target_id: str,
    detail: dict[str, Any] | None,
    ip_address: str,
) -> dict[str, Any]:
    return {
        "event_id": f"audit_{uuid4().hex[:16]}",
        "tenant_id": tenant_id or "*",
        "actor_user_id": actor_user_id or "unknown",
        "action": action.strip() or "unknown",
        "target_type": target_type.strip() or "unknown",
        "target_id": str(target_id or "").strip(),
        "detail": sanitize_audit_detail(detail or {}),
        "ip_address": _mask_ip_address(ip_address),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


_SECRET_KEY_PARTS = ("password", "secret", "token", "api_key", "apikey", "credential", "authorization", "cookie")
_CONTENT_KEYS = {
    "content",
    "contentpreview",
    "body",
    "report",
    "snapshot",
    "script",
    "source_code",
    "rows",
    "data",
    "payload_ref_content",
}


def sanitize_audit_detail(value: Any, *, _depth: int = 0) -> Any:
    """Keep audit metadata useful without copying secrets or business content."""

    if _depth >= 4:
        return _value_summary(value)
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 40:
                sanitized["_truncated_keys"] = len(value) - 40
                break
            normalized_key = str(key).strip().lower().replace("-", "_")
            if any(part in normalized_key for part in _SECRET_KEY_PARTS):
                sanitized[str(key)] = "[REDACTED]"
            elif normalized_key.replace("_", "") in _CONTENT_KEYS or normalized_key in _CONTENT_KEYS:
                sanitized[str(key)] = _value_summary(item)
            else:
                sanitized[str(key)] = sanitize_audit_detail(item, _depth=_depth + 1)
        return sanitized
    if isinstance(value, (list, tuple)):
        if len(value) > 20:
            return {"type": "list", "count": len(value), "sha256": _stable_hash(value)}
        return [sanitize_audit_detail(item, _depth=_depth + 1) for item in value]
    if isinstance(value, str) and len(value) > 500:
        return _value_summary(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return _value_summary(value)


def _value_summary(value: Any) -> dict[str, Any]:
    size = len(value) if hasattr(value, "__len__") else None
    return {
        "redacted": True,
        "type": type(value).__name__,
        "size": size,
        "sha256": _stable_hash(value),
    }


def _stable_hash(value: Any) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    except Exception:
        encoded = repr(value).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mask_ip_address(value: str) -> str:
    text = str(value or "").strip()
    parts = text.split(".")
    if len(parts) == 4 and all(part.isdigit() for part in parts):
        return ".".join((*parts[:3], "*"))
    if not text:
        return ""
    return f"hash:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"
