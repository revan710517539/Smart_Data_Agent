from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.platform.database.identity import PostgreSQLIdentityResolver


SUPPORTED_CROSS_TENANT_RESOURCE_TYPES = frozenset({"raw_table"})
SUPPORTED_CROSS_TENANT_ACTIONS = frozenset({"read"})


@dataclass(frozen=True)
class ResourceAccessScope:
    allowed: bool
    direct: bool = False
    field_scope: tuple[str, ...] = ()
    grant_ids: tuple[str, ...] = ()


class InMemoryTenantGovernanceStore:
    def __init__(self) -> None:
        self._topic_assignments: dict[str, dict[str, Any]] = {}
        self._resource_grants: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def close(self) -> None:
        return

    def list_topic_assignments(self, tenant_id: str, *, include_inactive: bool = True) -> list[dict[str, Any]]:
        with self._lock:
            rows = [dict(item) for item in self._topic_assignments.values() if item["tenant_id"] == tenant_id]
        return _filtered_records(rows, include_inactive=include_inactive)

    def upsert_topic_assignment(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            existing = next(
                (
                    item for item in self._topic_assignments.values()
                    if item["tenant_id"] == record["tenant_id"] and item["topic_skill_id"] == record["topic_skill_id"]
                ),
                None,
            )
            saved = {
                **(existing or {}),
                **record,
                "assignment_id": str((existing or {}).get("assignment_id") or record["assignment_id"]),
                "status": "active",
                "revoked_by": "",
                "revoked_at": "",
                "revoke_reason": "",
            }
            self._topic_assignments[saved["assignment_id"]] = saved
            return dict(saved)

    def revoke_topic_assignment(self, assignment_id: str, actor_user_id: str, reason: str) -> dict[str, Any]:
        with self._lock:
            current = self._topic_assignments.get(assignment_id)
            if current is None:
                raise KeyError("tenant_topic_assignment_not_found")
            saved = {
                **current,
                "status": "revoked",
                "revoked_by": actor_user_id,
                "revoked_at": _utc_now(),
                "revoke_reason": reason,
            }
            self._topic_assignments[assignment_id] = saved
            return dict(saved)

    def list_resource_grants(
        self,
        *,
        source_tenant_id: str = "",
        recipient_tenant_id: str = "",
        include_inactive: bool = True,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = [
                dict(item)
                for item in self._resource_grants.values()
                if (not source_tenant_id or item["source_tenant_id"] == source_tenant_id)
                and (not recipient_tenant_id or item["recipient_tenant_id"] == recipient_tenant_id)
            ]
        return _filtered_records(rows, include_inactive=include_inactive)

    def insert_resource_grant(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._resource_grants[record["grant_id"]] = dict(record)
        return dict(record)

    def revoke_resource_grant(self, grant_id: str, actor_user_id: str, reason: str) -> dict[str, Any]:
        with self._lock:
            current = self._resource_grants.get(grant_id)
            if current is None:
                raise KeyError("cross_tenant_resource_grant_not_found")
            saved = {
                **current,
                "status": "revoked",
                "revoked_by": actor_user_id,
                "revoked_at": _utc_now(),
                "revoke_reason": reason,
            }
            self._resource_grants[grant_id] = saved
            return dict(saved)


class SQLiteTenantGovernanceStore:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()

    def close(self) -> None:
        self._conn.close()

    def list_topic_assignments(self, tenant_id: str, *, include_inactive: bool = True) -> list[dict[str, Any]]:
        where = "tenant_id = ?" + ("" if include_inactive else " AND status = 'active'")
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM platform_tenant_topic_assignments WHERE {where} ORDER BY assigned_at, assignment_id",
                (tenant_id,),
            ).fetchall()
        return [_topic_record_from_row(row) for row in rows]

    def upsert_topic_assignment(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock, self._conn:
            current = self._conn.execute(
                "SELECT assignment_id FROM platform_tenant_topic_assignments WHERE tenant_id = ? AND topic_skill_id = ?",
                (record["tenant_id"], record["topic_skill_id"]),
            ).fetchone()
            assignment_id = str(current["assignment_id"]) if current else record["assignment_id"]
            self._conn.execute(
                """
                INSERT INTO platform_tenant_topic_assignments(
                    assignment_id, tenant_id, topic_skill_id, status, assigned_by, assigned_at,
                    expires_at, revoked_by, revoked_at, revoke_reason
                ) VALUES (?, ?, ?, 'active', ?, ?, ?, '', '', '')
                ON CONFLICT(tenant_id, topic_skill_id) DO UPDATE SET
                    status = 'active', assigned_by = excluded.assigned_by, assigned_at = excluded.assigned_at,
                    expires_at = excluded.expires_at, revoked_by = '', revoked_at = '', revoke_reason = ''
                """,
                (
                    assignment_id,
                    record["tenant_id"],
                    record["topic_skill_id"],
                    record["assigned_by"],
                    record["assigned_at"],
                    record["expires_at"],
                ),
            )
        return next(
            item
            for item in self.list_topic_assignments(record["tenant_id"], include_inactive=True)
            if item["assignment_id"] == assignment_id
        )

    def revoke_topic_assignment(self, assignment_id: str, actor_user_id: str, reason: str) -> dict[str, Any]:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                UPDATE platform_tenant_topic_assignments
                SET status = 'revoked', revoked_by = ?, revoked_at = ?, revoke_reason = ?
                WHERE assignment_id = ?
                """,
                (actor_user_id, _utc_now(), reason, assignment_id),
            )
            if cursor.rowcount != 1:
                raise KeyError("tenant_topic_assignment_not_found")
            row = self._conn.execute(
                "SELECT * FROM platform_tenant_topic_assignments WHERE assignment_id = ?", (assignment_id,)
            ).fetchone()
        return _topic_record_from_row(row)

    def list_resource_grants(
        self,
        *,
        source_tenant_id: str = "",
        recipient_tenant_id: str = "",
        include_inactive: bool = True,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if source_tenant_id:
            clauses.append("source_tenant_id = ?")
            params.append(source_tenant_id)
        if recipient_tenant_id:
            clauses.append("recipient_tenant_id = ?")
            params.append(recipient_tenant_id)
        if not include_inactive:
            clauses.append("status = 'active'")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM platform_cross_tenant_resource_grants{where} ORDER BY created_at, grant_id",
                tuple(params),
            ).fetchall()
        return [_grant_record_from_row(row) for row in rows]

    def insert_resource_grant(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_cross_tenant_resource_grants(
                    grant_id, source_tenant_id, recipient_tenant_id, resource_type, resource_key,
                    actions, field_scope, schema_fingerprint, purpose, status, effective_at, expires_at,
                    created_by, approved_by, created_at, revoked_by, revoked_at, revoke_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, '', '', '')
                """,
                (
                    record["grant_id"], record["source_tenant_id"], record["recipient_tenant_id"],
                    record["resource_type"], record["resource_key"], json.dumps(record["actions"]),
                    json.dumps(record["field_scope"]), record["schema_fingerprint"], record["purpose"],
                    record["effective_at"], record["expires_at"], record["created_by"],
                    record["approved_by"], record["created_at"],
                ),
            )
        return dict(record)

    def revoke_resource_grant(self, grant_id: str, actor_user_id: str, reason: str) -> dict[str, Any]:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                UPDATE platform_cross_tenant_resource_grants
                SET status = 'revoked', revoked_by = ?, revoked_at = ?, revoke_reason = ?
                WHERE grant_id = ?
                """,
                (actor_user_id, _utc_now(), reason, grant_id),
            )
            if cursor.rowcount != 1:
                raise KeyError("cross_tenant_resource_grant_not_found")
            row = self._conn.execute(
                "SELECT * FROM platform_cross_tenant_resource_grants WHERE grant_id = ?", (grant_id,)
            ).fetchone()
        return _grant_record_from_row(row)


class RelationalTenantGovernanceStore:
    """Normalized relational store; the production MySQL compatibility pool owns SQL translation."""

    def __init__(self, pool: Any) -> None:
        self.pool = pool

    def close(self) -> None:
        return

    def list_topic_assignments(self, tenant_id: str, *, include_inactive: bool = True) -> list[dict[str, Any]]:
        status = "" if include_inactive else " AND a.status = 'active'"
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT a.assignment_id, t.tenant_code AS tenant_id, a.topic_skill_id, a.status,
                       actor.external_subject AS assigned_by, a.assigned_at, a.expires_at,
                       revoker.external_subject AS revoked_by, a.revoked_at, a.revoke_reason
                FROM platform_tenant_topic_assignments a
                JOIN platform_tenants t ON t.tenant_id = a.tenant_id
                LEFT JOIN platform_user_profiles actor ON actor.user_id = a.assigned_by
                LEFT JOIN platform_user_profiles revoker ON revoker.user_id = a.revoked_by
                WHERE t.tenant_code = %s{status}
                ORDER BY a.assigned_at, a.assignment_id
                """,
                (tenant_id,),
            )
            rows = cursor.fetchall()
        return [_topic_record_from_row(row) for row in rows]

    def upsert_topic_assignment(self, record: dict[str, Any]) -> dict[str, Any]:
        with self.pool.transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, record["tenant_id"])
            actor_key = PostgreSQLIdentityResolver.user_id(connection, record["assigned_by"])
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_tenant_topic_assignments(
                        assignment_id, tenant_id, topic_skill_id, status, assigned_by, assigned_at,
                        expires_at, revoked_by, revoked_at, revoke_reason
                    ) VALUES (%s, %s, %s, 'active', %s, %s, %s, NULL, NULL, '')
                    ON CONFLICT (tenant_id, topic_skill_id) DO UPDATE SET
                        status = 'active', assigned_by = EXCLUDED.assigned_by,
                        assigned_at = EXCLUDED.assigned_at, expires_at = EXCLUDED.expires_at,
                        revoked_by = NULL, revoked_at = NULL, revoke_reason = ''
                    """,
                    (
                        record["assignment_id"], tenant_key, record["topic_skill_id"], actor_key,
                        record["assigned_at"], record["expires_at"] or None,
                    ),
                )
        return next(
            item
            for item in self.list_topic_assignments(record["tenant_id"], include_inactive=True)
            if item["topic_skill_id"] == record["topic_skill_id"]
        )

    def revoke_topic_assignment(self, assignment_id: str, actor_user_id: str, reason: str) -> dict[str, Any]:
        with self.pool.transaction() as connection:
            actor_key = PostgreSQLIdentityResolver.user_id(connection, actor_user_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_tenant_topic_assignments
                    SET status = 'revoked', revoked_by = %s, revoked_at = now(), revoke_reason = %s
                    WHERE assignment_id = %s
                    """,
                    (actor_key, reason, assignment_id),
                )
                if cursor.rowcount != 1:
                    raise KeyError("tenant_topic_assignment_not_found")
                cursor.execute(
                    """
                    SELECT a.assignment_id, t.tenant_code AS tenant_id, a.topic_skill_id, a.status,
                           assigned.external_subject AS assigned_by, a.assigned_at, a.expires_at,
                           revoked.external_subject AS revoked_by, a.revoked_at, a.revoke_reason
                    FROM platform_tenant_topic_assignments a
                    JOIN platform_tenants t ON t.tenant_id = a.tenant_id
                    LEFT JOIN platform_user_profiles assigned ON assigned.user_id = a.assigned_by
                    LEFT JOIN platform_user_profiles revoked ON revoked.user_id = a.revoked_by
                    WHERE a.assignment_id = %s
                    """,
                    (assignment_id,),
                )
                row = cursor.fetchone()
        return _topic_record_from_row(row)

    def list_resource_grants(
        self,
        *,
        source_tenant_id: str = "",
        recipient_tenant_id: str = "",
        include_inactive: bool = True,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if source_tenant_id:
            clauses.append("source.tenant_code = %s")
            params.append(source_tenant_id)
        if recipient_tenant_id:
            clauses.append("recipient.tenant_code = %s")
            params.append(recipient_tenant_id)
        if not include_inactive:
            clauses.append("g.status = 'active'")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT g.grant_id, source.tenant_code AS source_tenant_id,
                       recipient.tenant_code AS recipient_tenant_id, g.resource_type, g.resource_key,
                       g.actions, g.field_scope, g.schema_fingerprint, g.purpose, g.status,
                       g.effective_at, g.expires_at, creator.external_subject AS created_by,
                       approver.external_subject AS approved_by, g.created_at,
                       revoker.external_subject AS revoked_by, g.revoked_at, g.revoke_reason
                FROM platform_cross_tenant_resource_grants g
                JOIN platform_tenants source ON source.tenant_id = g.source_tenant_id
                JOIN platform_tenants recipient ON recipient.tenant_id = g.recipient_tenant_id
                LEFT JOIN platform_user_profiles creator ON creator.user_id = g.created_by
                LEFT JOIN platform_user_profiles approver ON approver.user_id = g.approved_by
                LEFT JOIN platform_user_profiles revoker ON revoker.user_id = g.revoked_by
                {where}
                ORDER BY g.created_at, g.grant_id
                """,
                tuple(params),
            )
            rows = cursor.fetchall()
        return [_grant_record_from_row(row) for row in rows]

    def insert_resource_grant(self, record: dict[str, Any]) -> dict[str, Any]:
        with self.pool.transaction() as connection:
            source_key = PostgreSQLIdentityResolver.tenant_id(connection, record["source_tenant_id"])
            recipient_key = PostgreSQLIdentityResolver.tenant_id(connection, record["recipient_tenant_id"])
            creator_key = PostgreSQLIdentityResolver.user_id(connection, record["created_by"])
            approver_key = PostgreSQLIdentityResolver.user_id(connection, record["approved_by"])
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_cross_tenant_resource_grants(
                        grant_id, source_tenant_id, recipient_tenant_id, resource_type, resource_key,
                        actions, field_scope, schema_fingerprint, purpose, status, effective_at, expires_at,
                        created_by, approved_by, created_at, revoked_by, revoked_at, revoke_reason
                    ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, 'active',
                              %s, %s, %s, %s, %s, NULL, NULL, '')
                    """,
                    (
                        record["grant_id"], source_key, recipient_key, record["resource_type"],
                        record["resource_key"], json.dumps(record["actions"]), json.dumps(record["field_scope"]),
                        record["schema_fingerprint"], record["purpose"], record["effective_at"],
                        record["expires_at"], creator_key, approver_key, record["created_at"],
                    ),
                )
        return dict(record)

    def revoke_resource_grant(self, grant_id: str, actor_user_id: str, reason: str) -> dict[str, Any]:
        with self.pool.transaction() as connection:
            actor_key = PostgreSQLIdentityResolver.user_id(connection, actor_user_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_cross_tenant_resource_grants
                    SET status = 'revoked', revoked_by = %s, revoked_at = now(), revoke_reason = %s
                    WHERE grant_id = %s
                    """,
                    (actor_key, reason, grant_id),
                )
                if cursor.rowcount != 1:
                    raise KeyError("cross_tenant_resource_grant_not_found")
        return next(item for item in self.list_resource_grants() if item["grant_id"] == grant_id)


class TenantScopeService:
    def __init__(self, store: Any, enforcer: Any, data_asset_store: Any, raw_table_source: Any | None = None) -> None:
        self.store = store
        self.enforcer = enforcer
        self.data_asset_store = data_asset_store
        self.raw_table_source = raw_table_source

    def close(self) -> None:
        self.store.close()

    def assign_topic(
        self,
        *,
        actor_user_id: str,
        tenant_id: str,
        topic_skill_id: str,
        active_tenant_ids: set[str],
        expires_at: str = "",
    ) -> dict[str, Any]:
        _require_active_tenant(tenant_id, active_tenant_ids)
        topic_id = _bounded_text(topic_skill_id, "tenant_topic_skill_id_required", 160)
        skills = self.data_asset_store.list_published_bundle(tenant_id).get("analysis_skills", [])
        topic = next(
            (
                item for item in skills
                if isinstance(item, dict)
                and str(item.get("id") or "") == topic_id
                and str(item.get("category") or "") == "主题"
                and item.get("enabled") is not False
            ),
            None,
        )
        if topic is None:
            raise ValueError("tenant_topic_skill_not_published")
        expiry = _optional_future_time(expires_at, "tenant_topic_expiry_invalid")
        return self.store.upsert_topic_assignment(
            {
                "assignment_id": str(uuid4()),
                "tenant_id": tenant_id,
                "topic_skill_id": topic_id,
                "status": "active",
                "assigned_by": actor_user_id,
                "assigned_at": _utc_now(),
                "expires_at": expiry,
                "revoked_by": "",
                "revoked_at": "",
                "revoke_reason": "",
            }
        )

    def revoke_topic(self, assignment_id: str, actor_user_id: str, reason: str) -> dict[str, Any]:
        return self.store.revoke_topic_assignment(
            _bounded_text(assignment_id, "tenant_topic_assignment_id_required", 80),
            actor_user_id,
            _bounded_text(reason, "tenant_governance_revoke_reason_required", 500),
        )

    def create_resource_grant(
        self,
        *,
        actor_user_id: str,
        source_tenant_id: str,
        recipient_tenant_id: str,
        resource_type: str,
        resource_key: str,
        actions: list[str],
        field_scope: list[str],
        schema_fingerprint: str,
        purpose: str,
        active_tenant_ids: set[str],
        effective_at: str = "",
        expires_at: str,
    ) -> dict[str, Any]:
        _require_active_tenant(source_tenant_id, active_tenant_ids)
        _require_active_tenant(recipient_tenant_id, active_tenant_ids)
        if source_tenant_id == recipient_tenant_id:
            raise ValueError("cross_tenant_grant_requires_distinct_tenants")
        kind = _bounded_text(resource_type, "cross_tenant_resource_type_required", 64)
        if kind not in SUPPORTED_CROSS_TENANT_RESOURCE_TYPES:
            raise ValueError("cross_tenant_resource_type_unsupported")
        key = _bounded_text(resource_key, "cross_tenant_resource_key_required", 200)
        if key == "*":
            raise ValueError("cross_tenant_resource_wildcard_forbidden")
        normalized_actions = _unique_strings(actions, 20, 64)
        if not normalized_actions or any(action not in SUPPORTED_CROSS_TENANT_ACTIONS for action in normalized_actions):
            raise ValueError("cross_tenant_actions_invalid")
        normalized_fields = _unique_strings(field_scope, 200, 160)
        if not normalized_fields:
            raise ValueError("cross_tenant_field_scope_required")
        fingerprint = _bounded_text(schema_fingerprint, "cross_tenant_schema_fingerprint_required", 64).lower()
        if len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
            raise ValueError("cross_tenant_schema_fingerprint_invalid")
        table = self._current_raw_table(source_tenant_id, key)
        if table is None:
            raise ValueError("cross_tenant_raw_table_not_found")
        if str(table.get("schemaFingerprint") or "") != fingerprint:
            raise ValueError("cross_tenant_schema_fingerprint_changed")
        available_fields = {
            str(field.get("fieldNameEn") or "")
            for field in table.get("fields", [])
            if isinstance(field, dict) and str(field.get("fieldNameEn") or "")
        }
        if not set(normalized_fields).issubset(available_fields):
            raise ValueError("cross_tenant_field_scope_invalid")
        reason = _bounded_text(purpose, "cross_tenant_purpose_required", 500)
        effective = _optional_time(effective_at) or _utc_now()
        expiry = _required_future_time(expires_at, "cross_tenant_expiry_invalid")
        if _parse_time(expiry) <= _parse_time(effective):
            raise ValueError("cross_tenant_expiry_invalid")
        now = _utc_now()
        duplicate = next(
            (
                item for item in self.store.list_resource_grants(
                    source_tenant_id=source_tenant_id,
                    recipient_tenant_id=recipient_tenant_id,
                    include_inactive=False,
                )
                if _record_is_active(item)
                and item["resource_type"] == kind
                and item["resource_key"] == key
                and set(item["actions"]) == set(normalized_actions)
                and set(item["field_scope"]) == set(normalized_fields)
                and item["schema_fingerprint"] == fingerprint
            ),
            None,
        )
        if duplicate is not None:
            raise ValueError("cross_tenant_resource_grant_duplicate")
        return self.store.insert_resource_grant(
            {
                "grant_id": str(uuid4()),
                "source_tenant_id": source_tenant_id,
                "recipient_tenant_id": recipient_tenant_id,
                "resource_type": kind,
                "resource_key": key,
                "actions": normalized_actions,
                "field_scope": normalized_fields,
                "schema_fingerprint": fingerprint,
                "purpose": reason,
                "status": "active",
                "effective_at": effective,
                "expires_at": expiry,
                "created_by": actor_user_id,
                "approved_by": actor_user_id,
                "created_at": now,
                "revoked_by": "",
                "revoked_at": "",
                "revoke_reason": "",
            }
        )

    def revoke_resource_grant(self, grant_id: str, actor_user_id: str, reason: str) -> dict[str, Any]:
        return self.store.revoke_resource_grant(
            _bounded_text(grant_id, "cross_tenant_resource_grant_id_required", 80),
            actor_user_id,
            _bounded_text(reason, "tenant_governance_revoke_reason_required", 500),
        )

    def revoke_tenant_scope(self, tenant_id: str, actor_user_id: str, reason: str) -> dict[str, int]:
        normalized_reason = _bounded_text(reason, "tenant_governance_revoke_reason_required", 500)
        topic_count = 0
        for assignment in self.store.list_topic_assignments(tenant_id, include_inactive=False):
            self.store.revoke_topic_assignment(str(assignment["assignment_id"]), actor_user_id, normalized_reason)
            topic_count += 1
        grants = {
            str(item["grant_id"]): item
            for item in [
                *self.store.list_resource_grants(source_tenant_id=tenant_id, include_inactive=False),
                *self.store.list_resource_grants(recipient_tenant_id=tenant_id, include_inactive=False),
            ]
        }
        for grant_id in grants:
            self.store.revoke_resource_grant(grant_id, actor_user_id, normalized_reason)
        return {"topic_assignments_revoked": topic_count, "resource_grants_revoked": len(grants)}

    def snapshot(self, tenant_id: str) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "topic_assignments": self.store.list_topic_assignments(tenant_id, include_inactive=True),
            "outgoing_grants": self.store.list_resource_grants(source_tenant_id=tenant_id, include_inactive=True),
            "incoming_grants": self.store.list_resource_grants(recipient_tenant_id=tenant_id, include_inactive=True),
        }

    def filter_analysis_skills(self, tenant_id: str, skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
        assignments = self.store.list_topic_assignments(tenant_id, include_inactive=True)
        if not assignments:
            return list(skills)
        active_topic_ids = {
            str(item["topic_skill_id"])
            for item in assignments
            if _record_is_active(item)
        }
        return [
            item
            for item in skills
            if str(item.get("category") or "") != "主题" or str(item.get("id") or "") in active_topic_ids
        ]

    def topic_assignments_configured(self, tenant_id: str) -> bool:
        return bool(self.store.list_topic_assignments(tenant_id, include_inactive=True))

    def granted_source_tenant_ids(
        self,
        *,
        user_id: str,
        recipient_tenant_id: str,
        active_tenant_ids: set[str],
        resource_type: str,
        action: str,
    ) -> set[str]:
        if recipient_tenant_id not in active_tenant_ids or not self._recipient_permission(user_id, recipient_tenant_id, resource_type, action):
            return set()
        return {
            str(item["source_tenant_id"])
            for item in self.store.list_resource_grants(
                recipient_tenant_id=recipient_tenant_id,
                include_inactive=False,
            )
            if _record_is_active(item)
            and item["resource_type"] == resource_type
            and action in item["actions"]
            and str(item["source_tenant_id"]) in active_tenant_ids
        }

    def resolve_resource_access(
        self,
        *,
        user_id: str,
        recipient_tenant_id: str,
        source_tenant_id: str,
        active_tenant_ids: set[str],
        direct_source_tenant_ids: set[str],
        resource_type: str,
        resource_key: str,
        action: str,
        schema_fingerprint: str = "",
        requested_fields: set[str] | None = None,
    ) -> ResourceAccessScope:
        if source_tenant_id in direct_source_tenant_ids:
            return ResourceAccessScope(allowed=True, direct=True)
        if source_tenant_id not in active_tenant_ids or recipient_tenant_id not in active_tenant_ids:
            return ResourceAccessScope(allowed=False)
        if not self._recipient_permission(user_id, recipient_tenant_id, resource_type, action):
            return ResourceAccessScope(allowed=False)
        scopes = self.resource_grant_scopes(
            user_id=user_id,
            recipient_tenant_id=recipient_tenant_id,
            active_tenant_ids=active_tenant_ids,
            resource_type=resource_type,
            action=action,
        )
        candidates = [
            scope
            for (tenant_id, key, fingerprint), scope in scopes.items()
            if tenant_id == source_tenant_id
            and key == resource_key
            and (not schema_fingerprint or fingerprint == schema_fingerprint)
        ]
        fields = {field for scope in candidates for field in scope.field_scope}
        requested = {str(field) for field in (requested_fields or set()) if str(field)}
        if not candidates or (requested and not requested.issubset(fields)):
            return ResourceAccessScope(allowed=False)
        return ResourceAccessScope(
            allowed=True,
            field_scope=tuple(sorted(fields)),
            grant_ids=tuple(sorted({grant_id for scope in candidates for grant_id in scope.grant_ids})),
        )

    def resource_grant_scopes(
        self,
        *,
        user_id: str,
        recipient_tenant_id: str,
        active_tenant_ids: set[str],
        resource_type: str,
        action: str,
    ) -> dict[tuple[str, str, str], ResourceAccessScope]:
        if recipient_tenant_id not in active_tenant_ids or not self._recipient_permission(
            user_id, recipient_tenant_id, resource_type, action
        ):
            return {}
        grouped: dict[tuple[str, str, str], dict[str, set[str]]] = {}
        for item in self.store.list_resource_grants(
            recipient_tenant_id=recipient_tenant_id,
            include_inactive=False,
        ):
            source_tenant_id = str(item["source_tenant_id"])
            if (
                not _record_is_active(item)
                or source_tenant_id not in active_tenant_ids
                or item["resource_type"] != resource_type
                or action not in item["actions"]
            ):
                continue
            key = (source_tenant_id, str(item["resource_key"]), str(item["schema_fingerprint"]))
            bucket = grouped.setdefault(key, {"fields": set(), "grants": set()})
            bucket["fields"].update(str(field) for field in item["field_scope"])
            bucket["grants"].add(str(item["grant_id"]))
        return {
            key: ResourceAccessScope(
                allowed=True,
                field_scope=tuple(sorted(bucket["fields"])),
                grant_ids=tuple(sorted(bucket["grants"])),
            )
            for key, bucket in grouped.items()
        }

    def _recipient_permission(self, user_id: str, tenant_id: str, resource_type: str, action: str) -> bool:
        object_id = "asset:*" if resource_type == "raw_table" else f"{resource_type}:*"
        return bool(self.enforcer.enforce(user_id, tenant_id, object_id, action))

    def _current_raw_table(self, tenant_id: str, source_key: str) -> dict[str, Any] | None:
        if self.raw_table_source is None:
            raise RuntimeError("cross_tenant_raw_table_catalog_unavailable")
        catalog = self.raw_table_source.for_tenant(tenant_id)
        if not getattr(catalog, "catalog_ready", True):
            prime = getattr(catalog, "prime_catalog", None)
            if callable(prime):
                prime()
        for table in catalog.table_assets():
            if isinstance(table, dict) and str(table.get("sourceKey") or "") == source_key:
                return dict(table)
        return None


def build_tenant_scope_service(
    *,
    enforcer: Any,
    data_asset_store: Any,
    db_path: str | Path | None = None,
    relational_pool: Any | None = None,
    raw_table_source: Any | None = None,
) -> TenantScopeService:
    if relational_pool is not None:
        store: Any = RelationalTenantGovernanceStore(relational_pool)
    elif db_path is not None:
        store = SQLiteTenantGovernanceStore(db_path)
    else:
        store = InMemoryTenantGovernanceStore()
    return TenantScopeService(store, enforcer, data_asset_store, raw_table_source)


def _filtered_records(rows: list[dict[str, Any]], *, include_inactive: bool) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda item: (str(item.get("created_at") or item.get("assigned_at") or ""), str(item)))
    return ordered if include_inactive else [item for item in ordered if item.get("status") == "active"]


def _record_is_active(item: dict[str, Any]) -> bool:
    if str(item.get("status") or "") != "active":
        return False
    now = datetime.now(timezone.utc)
    effective = _parse_time(str(item.get("effective_at") or ""), optional=True)
    expiry = _parse_time(str(item.get("expires_at") or ""), optional=True)
    return (effective is None or effective <= now) and (expiry is None or expiry > now)


def _topic_record_from_row(row: Any) -> dict[str, Any]:
    return {
        "assignment_id": str(_row_value(row, "assignment_id", 0)),
        "tenant_id": str(_row_value(row, "tenant_id", 1)),
        "topic_skill_id": str(_row_value(row, "topic_skill_id", 2)),
        "status": str(_row_value(row, "status", 3)),
        "assigned_by": str(_row_value(row, "assigned_by", 4) or ""),
        "assigned_at": _iso(_row_value(row, "assigned_at", 5)),
        "expires_at": _iso(_row_value(row, "expires_at", 6)),
        "revoked_by": str(_row_value(row, "revoked_by", 7) or ""),
        "revoked_at": _iso(_row_value(row, "revoked_at", 8)),
        "revoke_reason": str(_row_value(row, "revoke_reason", 9) or ""),
    }


def _grant_record_from_row(row: Any) -> dict[str, Any]:
    return {
        "grant_id": str(_row_value(row, "grant_id", 0)),
        "source_tenant_id": str(_row_value(row, "source_tenant_id", 1)),
        "recipient_tenant_id": str(_row_value(row, "recipient_tenant_id", 2)),
        "resource_type": str(_row_value(row, "resource_type", 3)),
        "resource_key": str(_row_value(row, "resource_key", 4)),
        "actions": _json_list(_row_value(row, "actions", 5)),
        "field_scope": _json_list(_row_value(row, "field_scope", 6)),
        "schema_fingerprint": str(_row_value(row, "schema_fingerprint", 7) or ""),
        "purpose": str(_row_value(row, "purpose", 8) or ""),
        "status": str(_row_value(row, "status", 9)),
        "effective_at": _iso(_row_value(row, "effective_at", 10)),
        "expires_at": _iso(_row_value(row, "expires_at", 11)),
        "created_by": str(_row_value(row, "created_by", 12) or ""),
        "approved_by": str(_row_value(row, "approved_by", 13) or ""),
        "created_at": _iso(_row_value(row, "created_at", 14)),
        "revoked_by": str(_row_value(row, "revoked_by", 15) or ""),
        "revoked_at": _iso(_row_value(row, "revoked_at", 16)),
        "revoke_reason": str(_row_value(row, "revoke_reason", 17) or ""),
    }


def _json_list(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return [str(item) for item in value] if isinstance(value, (list, tuple)) else []


def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict) or hasattr(row, "keys"):
        try:
            return row[key]
        except (KeyError, IndexError):
            pass
    return row[index]


def _require_active_tenant(tenant_id: str, active_tenant_ids: set[str]) -> None:
    if not tenant_id or tenant_id not in active_tenant_ids:
        raise ValueError("tenant_governance_tenant_not_active")


def _bounded_text(value: Any, error: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(error)
    if len(text) > maximum:
        raise ValueError(error)
    return text


def _unique_strings(values: Any, maximum_items: int, maximum_length: int) -> list[str]:
    if not isinstance(values, list) or len(values) > maximum_items:
        return []
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or len(text) > maximum_length:
            return []
        if text not in result:
            result.append(text)
    return result


def _required_future_time(value: str, error: str) -> str:
    parsed = _parse_time(value, optional=True)
    if parsed is None or parsed <= datetime.now(timezone.utc):
        raise ValueError(error)
    return parsed.isoformat()


def _optional_future_time(value: str, error: str) -> str:
    if not str(value or "").strip():
        return ""
    return _required_future_time(value, error)


def _optional_time(value: str) -> str:
    parsed = _parse_time(value, optional=True)
    return parsed.isoformat() if parsed is not None else ""


def _parse_time(value: str, *, optional: bool = False) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        if optional:
            return None
        raise ValueError("timestamp_required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp_invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp_timezone_required")
    return parsed.astimezone(timezone.utc)


def _iso(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, datetime):
        parsed = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return parsed.isoformat()
    try:
        parsed = _parse_time(str(value))
    except ValueError:
        return str(value)
    return parsed.isoformat() if parsed is not None else ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
