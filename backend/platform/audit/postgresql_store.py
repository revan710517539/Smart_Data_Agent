from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.postgresql import PostgreSQLConnectionPool

from .store import AuditEventStore, _normalize_event


class PostgreSQLAuditEventStore(AuditEventStore):
    """Append-only production audit store using sanitized, hash-bound metadata."""

    def __init__(self, pool: PostgreSQLConnectionPool, *, owns_pool: bool = False) -> None:
        self.pool = pool
        self.owns_pool = owns_pool

    def close(self) -> None:
        if self.owns_pool:
            self.pool.close()

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
        metadata = dict(event["detail"])
        if event["ip_address"]:
            metadata["ip_address"] = event["ip_address"]
        outcome = str(metadata.pop("outcome", "success"))
        if outcome not in {"success", "denied", "failed"}:
            outcome = "success"
        request_id = str(metadata.pop("request_id", "") or "")[:100] or None
        trace_id = str(metadata.pop("trace_id", "") or "")[:100] or None
        event_hash = _event_hash(
            tenant_id, actor_user_id, event["action"], event["target_type"],
            event["target_id"], outcome, metadata, event["created_at"],
        )
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, actor_user_id, required=False)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_audit_events(
                        tenant_id, actor_user_id, event_type, resource_type, resource_id,
                        action, outcome, request_id, trace_id, metadata, event_hash,
                        occurred_at, created_by
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::timestamptz, %s
                    ) RETURNING audit_event_id
                    """,
                    (
                        tenant_key, actor_key, f"{event['target_type']}.{event['action']}"[:120],
                        event["target_type"][:120], event["target_id"][:200] or None,
                        event["action"][:64], outcome, request_id, trace_id, _json(metadata),
                        event_hash, event["created_at"], actor_key,
                    ),
                )
                row = cursor.fetchone()
        return {**event, "event_id": str(_value(row, "audit_event_id", 0)), "detail": metadata}

    def list(self, tenant_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit or 50), 200))
        bounded_offset = max(0, int(offset or 0))
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT a.audit_event_id, t.tenant_code,
                           COALESCE(u.external_subject, 'unknown') AS actor_user_code,
                           a.action, a.resource_type, COALESCE(a.resource_id, '') AS resource_id,
                           a.metadata, a.occurred_at
                    FROM platform_audit_events a
                    JOIN platform_tenants t ON t.tenant_id = a.tenant_id
                    LEFT JOIN platform_user_profiles u ON u.user_id = a.actor_user_id
                    WHERE a.tenant_id = %s
                    ORDER BY a.occurred_at DESC, a.audit_event_id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (tenant_key, bounded_limit, bounded_offset),
                )
                rows = cursor.fetchall()
        return [self._from_row(row) for row in rows]

    def count(self, tenant_id: str) -> int:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) AS count FROM platform_audit_events WHERE tenant_id = %s",
                    (tenant_key,),
                )
                row = cursor.fetchone()
        return int(_value(row, "count", 0) or 0)

    def list_for_tenants(self, tenant_ids: list[str], limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit or 50), 200))
        bounded_offset = max(0, int(offset or 0))
        with self.pool.connection() as connection:
            tenant_keys = [PostgreSQLIdentityResolver.tenant_id(connection, tenant_id) for tenant_id in tenant_ids]
            if not tenant_keys:
                return []
            placeholders = ", ".join("%s" for _ in tenant_keys)
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT a.audit_event_id, t.tenant_code,
                           COALESCE(u.external_subject, 'unknown') AS actor_user_code,
                           a.action, a.resource_type, COALESCE(a.resource_id, '') AS resource_id,
                           a.metadata, a.occurred_at
                    FROM platform_audit_events a
                    JOIN platform_tenants t ON t.tenant_id = a.tenant_id
                    LEFT JOIN platform_user_profiles u ON u.user_id = a.actor_user_id
                    WHERE a.tenant_id IN ({placeholders})
                    ORDER BY a.occurred_at DESC, a.audit_event_id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (*tenant_keys, bounded_limit, bounded_offset),
                )
                rows = cursor.fetchall()
        return [self._from_row(row) for row in rows]

    def count_for_tenants(self, tenant_ids: list[str]) -> int:
        with self.pool.connection() as connection:
            tenant_keys = [PostgreSQLIdentityResolver.tenant_id(connection, tenant_id) for tenant_id in tenant_ids]
            if not tenant_keys:
                return 0
            placeholders = ", ".join("%s" for _ in tenant_keys)
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) AS count FROM platform_audit_events WHERE tenant_id IN ({placeholders})",
                    tenant_keys,
                )
                row = cursor.fetchone()
        return int(_value(row, "count", 0) or 0)

    @staticmethod
    def _from_row(row: Any) -> dict[str, Any]:
        metadata = _value(row, "metadata", 6) or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        metadata = dict(metadata)
        ip_address = str(metadata.pop("ip_address", "") or "")
        occurred_at = _value(row, "occurred_at", 7)
        return {
            "event_id": str(_value(row, "audit_event_id", 0)),
            "tenant_id": str(_value(row, "tenant_code", 1)),
            "actor_user_id": str(_value(row, "actor_user_code", 2)),
            "action": str(_value(row, "action", 3)),
            "target_type": str(_value(row, "resource_type", 4)),
            "target_id": str(_value(row, "resource_id", 5)),
            "detail": metadata,
            "ip_address": ip_address,
            "created_at": occurred_at.isoformat() if isinstance(occurred_at, datetime) else str(occurred_at),
        }

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self.pool.connection() as connection:
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise


def _event_hash(*values: Any) -> str:
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]
