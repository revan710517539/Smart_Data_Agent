from __future__ import annotations

import json
from typing import Any

from backend.platform.kernel.isolation import assert_account_write, is_visible_to, normalize_scope
from backend.platform.kernel.models import Capability, CapabilityStatus, new_id, utc_now
from backend.platform.kernel.store import capability_fingerprint


class MySQLAccountCapabilityStore:
    """Durable account-keyed capability store. User rows are filtered in SQL."""

    def __init__(self, pool: Any) -> None:
        self.pool = pool

    def close(self) -> None:
        return None

    def upsert(self, actor_user_id: str, capability: Capability) -> Capability:
        assert_account_write(capability.tenant_id, actor_user_id, capability)
        fingerprint = capability.fingerprint or capability_fingerprint(
            {"kind": capability.kind, "trigger": capability.trigger, "body": capability.body}
        )
        stored = Capability(
            capability_id=capability.capability_id,
            kind=capability.kind,
            runtime_type=capability.runtime_type,
            tenant_id=capability.tenant_id,
            owner_scope=normalize_scope(capability.owner_scope),
            owner_id=capability.owner_id,
            title=capability.title,
            description=capability.description,
            version=capability.version,
            status=capability.status,
            trigger=dict(capability.trigger),
            body=dict(capability.body),
            fingerprint=fingerprint,
            permission_scope=tuple(capability.permission_scope),
            created_by=capability.created_by or actor_user_id,
        )
        now = utc_now()
        with self.pool.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_account_capabilities(
                      tenant_id, owner_scope, owner_id, capability_id, version, kind, runtime_type,
                      status, title, description, trigger_json, body_json, permission_scope_json,
                      fingerprint, created_by, created_at, updated_at
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                      kind=VALUES(kind), runtime_type=VALUES(runtime_type), status=VALUES(status),
                      title=VALUES(title), description=VALUES(description), trigger_json=VALUES(trigger_json),
                      body_json=VALUES(body_json), permission_scope_json=VALUES(permission_scope_json),
                      fingerprint=VALUES(fingerprint), updated_at=VALUES(updated_at)
                    """,
                    (
                        stored.tenant_id,
                        stored.owner_scope,
                        stored.owner_id,
                        stored.capability_id,
                        stored.version,
                        stored.kind,
                        stored.runtime_type,
                        stored.status,
                        stored.title,
                        stored.description,
                        json.dumps(stored.trigger, ensure_ascii=False),
                        json.dumps(stored.body, ensure_ascii=False),
                        json.dumps(stored.permission_scope, ensure_ascii=False),
                        stored.fingerprint,
                        stored.created_by,
                        now,
                        now,
                    ),
                )
        return stored

    def get(self, tenant_id: str, owner_scope: str, owner_id: str, capability_id: str) -> Capability | None:
        with self.pool.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM platform_account_capabilities
                    WHERE tenant_id=%s AND owner_scope=%s AND owner_id=%s AND capability_id=%s
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (tenant_id, normalize_scope(owner_scope), owner_id, capability_id),
                )
                row = cursor.fetchone()
        return _row_to_capability(row) if row else None

    def list_visible(
        self,
        tenant_id: str,
        user_id: str,
        *,
        statuses: tuple[str, ...] = ("active",),
        role_ids: tuple[str, ...] = (),
        org_ids: tuple[str, ...] = (),
    ) -> list[Capability]:
        placeholders = ",".join(["%s"] * len(statuses))
        with self.pool.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT * FROM platform_account_capabilities
                    WHERE tenant_id=%s AND status IN ({placeholders})
                    """,
                    (tenant_id, *statuses),
                )
                rows = list(cursor.fetchall() or [])
        capabilities = [_row_to_capability(row) for row in rows]
        return [
            item
            for item in capabilities
            if is_visible_to(item, tenant_id, user_id, role_ids=role_ids, org_ids=org_ids)
        ]

    def list_user_active(self, tenant_id: str, *, status: CapabilityStatus = "active") -> list[Capability]:
        with self.pool.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM platform_account_capabilities
                    WHERE tenant_id=%s AND owner_scope='user' AND status=%s
                    """,
                    (tenant_id, status),
                )
                rows = list(cursor.fetchall() or [])
        return [_row_to_capability(row) for row in rows]

    def save_episode(self, episode: dict[str, Any]) -> dict[str, Any]:
        record = dict(episode)
        record.setdefault("episode_id", new_id("ep"))
        now = utc_now()
        with self.pool.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_runtime_episodes(
                      episode_id, tenant_id, user_id, session_id, parent_episode_id,
                      pack_snapshot_id, status, task_id, created_at, updated_at
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                      status=VALUES(status), pack_snapshot_id=VALUES(pack_snapshot_id),
                      task_id=VALUES(task_id), updated_at=VALUES(updated_at)
                    """,
                    (
                        record["episode_id"],
                        record.get("tenant_id") or "",
                        record.get("user_id") or "",
                        record.get("session_id") or "",
                        record.get("parent_episode_id"),
                        record.get("pack_snapshot_id") or "",
                        record.get("status") or "running",
                        record.get("task_id") or "",
                        now,
                        now,
                    ),
                )
        return record

    def save_pack(self, pack: dict[str, Any]) -> dict[str, Any]:
        record = dict(pack)
        created_at = str(record.get("created_at") or utc_now())
        with self.pool.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_capability_pack_snapshots(
                      snapshot_id, tenant_id, user_id, entries_json, entry_count, content_hash, created_at
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE snapshot_id=VALUES(snapshot_id)
                    """,
                    (
                        record["snapshot_id"],
                        record["tenant_id"],
                        record["user_id"],
                        json.dumps(record.get("entries") or [], ensure_ascii=False),
                        int(record.get("entry_count") or 0),
                        record.get("content_hash") or "",
                        created_at,
                    ),
                )
        return record

    def get_pack(self, tenant_id: str, user_id: str, snapshot_id: str) -> dict[str, Any] | None:
        with self.pool.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM platform_capability_pack_snapshots WHERE snapshot_id=%s",
                    (snapshot_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        record = dict(row)
        if record.get("tenant_id") != tenant_id or record.get("user_id") != user_id:
            raise PermissionError("capability_pack_account_isolation")
        entries = record.get("entries_json") or []
        if isinstance(entries, str):
            entries = json.loads(entries)
        return {**record, "entries": entries}

    def get_episode(self, tenant_id: str, user_id: str, episode_id: str) -> dict[str, Any] | None:
        with self.pool.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM platform_runtime_episodes WHERE episode_id=%s",
                    (episode_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        item = dict(row)
        if item.get("tenant_id") != tenant_id or item.get("user_id") != user_id:
            raise PermissionError("episode_account_isolation")
        return item

    def record_eval(self, payload: dict[str, Any]) -> dict[str, Any]:
        record = dict(payload)
        record.setdefault("eval_id", new_id("eval"))
        record.setdefault("created_at", utc_now())
        with self.pool.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_capability_evals(
                      eval_id, tenant_id, user_id, capability_id, episode_id, metric, score, status, detail_json, created_at
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        record["eval_id"],
                        record.get("tenant_id") or "",
                        record.get("user_id") or "",
                        record.get("capability_id") or "",
                        record.get("episode_id") or "",
                        record.get("metric") or "episode",
                        record.get("score"),
                        record.get("status") or "",
                        json.dumps(record.get("detail") or {}, ensure_ascii=False),
                        record["created_at"],
                    ),
                )
        return record

    def list_evals(self, tenant_id: str, capability_id: str | None = None) -> list[dict[str, Any]]:
        with self.pool.transaction() as connection:
            with connection.cursor() as cursor:
                if capability_id:
                    cursor.execute(
                        "SELECT * FROM platform_capability_evals WHERE tenant_id=%s AND capability_id=%s ORDER BY created_at DESC",
                        (tenant_id, capability_id),
                    )
                else:
                    cursor.execute(
                        "SELECT * FROM platform_capability_evals WHERE tenant_id=%s ORDER BY created_at DESC LIMIT 200",
                        (tenant_id,),
                    )
                rows = list(cursor.fetchall() or [])
        return [dict(row) for row in rows]


def _row_to_capability(row: Any) -> Capability:
    item = dict(row)
    trigger = item.get("trigger_json") or {}
    body = item.get("body_json") or {}
    permission_scope = item.get("permission_scope_json") or []
    if isinstance(trigger, str):
        trigger = json.loads(trigger)
    if isinstance(body, str):
        body = json.loads(body)
    if isinstance(permission_scope, str):
        permission_scope = json.loads(permission_scope)
    return Capability(
        capability_id=str(item["capability_id"]),
        kind=item["kind"],
        runtime_type=item["runtime_type"],
        tenant_id=str(item["tenant_id"]),
        owner_scope=item["owner_scope"],
        owner_id=str(item["owner_id"]),
        title=str(item.get("title") or ""),
        description=str(item.get("description") or ""),
        version=str(item.get("version") or "1.0.0"),
        status=item.get("status") or "candidate",
        trigger=trigger if isinstance(trigger, dict) else {},
        body=body if isinstance(body, dict) else {},
        fingerprint=str(item.get("fingerprint") or ""),
        permission_scope=tuple(str(value) for value in permission_scope if str(value).strip()),
        created_by=str(item.get("created_by") or ""),
    )
