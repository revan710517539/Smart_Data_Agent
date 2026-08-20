from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.postgresql import PostgreSQLConnectionPool

from .store import (
    ASSET_BUNDLE_KEYS,
    _asset_status,
    _governed_asset_payload,
    _item_title,
    _normalize_asset_payload_for_read,
    _normalize_item,
    _require_review_decision,
    _require_deletable_asset,
    _require_valid_type,
    _sort_key,
    _raw_table_external_reference_record,
    _validate_asset_schema,
    visible_items_for_tenant,
)


class PostgreSQLDataAssetStore:
    """Versioned, four-eyes production store for the existing data-assets UI."""

    def __init__(self, pool: PostgreSQLConnectionPool, *, owns_pool: bool = False) -> None:
        self.pool = pool
        self.owns_pool = owns_pool

    def close(self) -> None:
        if self.owns_pool:
            self.pool.close()

    def list_bundle(self, tenant_id: str) -> dict[str, list[dict[str, Any]]]:
        return self._bundle(tenant_id, published=False)

    def list_published_bundle(self, tenant_id: str) -> dict[str, list[dict[str, Any]]]:
        return self._bundle(tenant_id, published=True)

    def list_raw_table_external_references(self, tenant_id: str) -> dict[str, dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT ref.source_key, ref.mode, ref.schema_fingerprint,
                           actor.external_subject AS updated_by, ref.updated_at
                    FROM platform_raw_table_external_references ref
                    LEFT JOIN platform_user_profiles actor ON actor.user_id = ref.updated_by
                    WHERE ref.tenant_id = %s
                    """,
                    (tenant_key,),
                )
                rows = list(cursor.fetchall())
        return {
            str(_value(row, "source_key", 0)): {
                "sourceKey": str(_value(row, "source_key", 0)),
                "mode": str(_value(row, "mode", 1)),
                "schemaFingerprint": str(_value(row, "schema_fingerprint", 2)),
                "updatedBy": str(_value(row, "updated_by", 3) or ""),
                "updatedAt": _iso(_value(row, "updated_at", 4)),
            }
            for row in rows
        }

    def set_raw_table_external_reference(
        self, tenant_id: str, source_key: str, mode: str, schema_fingerprint: str, updated_by: str,
    ) -> dict[str, Any]:
        record = _raw_table_external_reference_record(source_key, mode, schema_fingerprint, updated_by)
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, updated_by)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_raw_table_external_references(
                        tenant_id, source_key, mode, schema_fingerprint, updated_by
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, source_key) DO UPDATE SET
                        mode = EXCLUDED.mode, schema_fingerprint = EXCLUDED.schema_fingerprint,
                        updated_by = EXCLUDED.updated_by, updated_at = now()
                    RETURNING updated_at
                    """,
                    (tenant_key, record["sourceKey"], record["mode"], record["schemaFingerprint"], actor_key),
                )
                record["updatedAt"] = _iso(_value(cursor.fetchone(), "updated_at", 0))
        return record

    def seed_defaults(self, tenant_id: str, updated_by: str = "development_seed") -> None:
        raise RuntimeError("production_data_assets_must_be_explicitly_imported_and_reviewed")

    def upsert_item(
        self,
        tenant_id: str,
        item_type: str,
        item: dict[str, Any],
        updated_by: str | None = None,
        lifecycle_status: str | None = None,
    ) -> dict[str, Any]:
        normalized = _normalize_item(item_type, item, updated_by)
        _validate_asset_schema(item_type, normalized)
        status = _asset_status(lifecycle_status)
        if not updated_by:
            raise ValueError("data_asset_submitter_required")
        payload_json = _json(normalized)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, updated_by)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT asset_item_id, lock_version,
                           COALESCE((SELECT MAX(version_number) FROM platform_data_asset_versions v
                                     WHERE v.asset_item_id = i.asset_item_id), 0) AS current_version
                    FROM platform_data_asset_items i
                    WHERE tenant_id = %s AND item_type = %s AND item_code = %s
                    FOR UPDATE
                    """,
                    (tenant_key, item_type, normalized["id"]),
                )
                current = cursor.fetchone()
                version_number = int(_value(current, "current_version", 2) or 0) + 1 if current else 1
                lock_version = int(_value(current, "lock_version", 1) or 0) + 1 if current else 1
                cursor.execute(
                    """
                    INSERT INTO platform_data_asset_items(
                        tenant_id, item_type, item_code, item_name, payload, status, created_by
                    ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
                    ON CONFLICT (tenant_id, item_type, item_code) DO UPDATE SET
                        item_name = EXCLUDED.item_name, payload = EXCLUDED.payload,
                        status = EXCLUDED.status, updated_at = now(),
                        lock_version = platform_data_asset_items.lock_version + 1
                    RETURNING asset_item_id, payload
                    """,
                    (
                        tenant_key, item_type, normalized["id"], _item_title(item_type, normalized),
                        payload_json, status, actor_key,
                    ),
                )
                returned_item = cursor.fetchone()
                item_key = _value(returned_item, "asset_item_id", 0)
                if status == "active" and item_type == "topic_table":
                    self._publish_topic_table(
                        connection,
                        tenant_key=tenant_key,
                        actor_key=actor_key,
                        payload=normalized,
                        version_number=version_number,
                    )
                if status == "active":
                    cursor.execute(
                        """
                        UPDATE platform_data_asset_versions
                        SET status = 'archived', updated_at = now(), lock_version = lock_version + 1
                        WHERE asset_item_id = %s AND status = 'active'
                        """,
                        (item_key,),
                    )
                cursor.execute(
                    """
                    INSERT INTO platform_data_asset_versions(
                        tenant_id, asset_item_id, version_number, schema_version,
                        payload, payload_hash, status, submitted_by, submitted_at,
                        reviewed_by, reviewed_at, created_by
                    ) VALUES (
                        %s, %s, %s, '1.0', %s::jsonb, %s, %s, %s, now(),
                        CASE WHEN %s = 'active' THEN %s END,
                        CASE WHEN %s = 'active' THEN now() END, %s
                    )
                    """,
                    (
                        tenant_key, item_key, version_number, payload_json, payload_hash,
                        status, actor_key, status, actor_key, status, actor_key,
                    ),
                )
        return _governed_asset_payload(
            normalized,
            status=status,
            version_number=version_number,
            submitted_by=updated_by,
            lock_version=lock_version,
            reviewed_by=updated_by if status == "active" else "",
            reviewed_at=_now_text() if status == "active" else "",
            published_at=_now_text() if status == "active" else "",
        )

    def get_item(self, tenant_id: str, item_type: str, item_id: str) -> dict[str, Any] | None:
        _require_valid_type(item_type)
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            rows = self._rows(
                connection,
                "i.tenant_id = %s AND i.item_type = %s AND i.item_code = %s",
                (tenant_key, item_type, item_id),
                published=False,
            )
        return self._asset_from_row(item_type, rows[0]) if rows else None

    def review_item(
        self,
        tenant_id: str,
        item_type: str,
        item_id: str,
        *,
        decision: str,
        reviewer_user_id: str,
        comments: str = "",
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        _require_valid_type(item_type)
        _require_review_decision(decision)
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            reviewer_key = PostgreSQLIdentityResolver.user_id(connection, reviewer_user_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT i.asset_item_id, i.status,
                           v.asset_version_id, v.version_number, v.status AS version_status,
                           v.submitted_by, v.payload
                    FROM platform_data_asset_items i
                    JOIN platform_data_asset_versions v ON v.asset_item_id = i.asset_item_id
                    WHERE i.tenant_id = %s AND i.item_type = %s AND i.item_code = %s
                    ORDER BY v.version_number DESC LIMIT 1 FOR UPDATE OF i, v
                    """,
                    (tenant_key, item_type, item_id),
                )
                row = cursor.fetchone()
                if not row:
                    raise KeyError("data_asset_not_found")
                version_number = int(_value(row, "version_number", 3))
                if expected_version is not None and version_number != int(expected_version):
                    raise RuntimeError("data_asset_version_conflict")
                if str(_value(row, "version_status", 4)) not in {"draft", "review"}:
                    raise RuntimeError("data_asset_not_reviewable")
                if _value(row, "submitted_by", 5) == reviewer_key:
                    raise PermissionError("data_asset_four_eyes_required")
                next_status = "active" if decision == "approved" else "rejected"
                if next_status == "active":
                    cursor.execute(
                        """
                        UPDATE platform_data_asset_versions
                        SET status = 'archived', updated_at = now(), lock_version = lock_version + 1
                        WHERE asset_item_id = %s AND status = 'active' AND asset_version_id <> %s
                        """,
                        (_value(row, "asset_item_id", 0), _value(row, "asset_version_id", 2)),
                    )
                cursor.execute(
                    """
                    UPDATE platform_data_asset_versions
                    SET status = %s, reviewed_by = %s, reviewed_at = now(), review_comment = %s,
                        updated_at = now(), lock_version = lock_version + 1
                    WHERE asset_version_id = %s AND status IN ('draft','review')
                    """,
                    (
                        next_status, reviewer_key, str(comments or "")[:2000],
                        _value(row, "asset_version_id", 2),
                    ),
                )
                if next_status == "active" and item_type == "topic_table":
                    payload = _value(row, "payload", 6)
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    self._publish_topic_table(
                        connection,
                        tenant_key=tenant_key,
                        actor_key=reviewer_key,
                        payload=_normalize_asset_payload_for_read(item_type, dict(payload)),
                        version_number=version_number,
                    )
                if cursor.rowcount != 1:
                    raise RuntimeError("data_asset_concurrent_review")
                cursor.execute(
                    """
                    UPDATE platform_data_asset_items
                    SET status = %s, updated_at = now(), lock_version = lock_version + 1
                    WHERE asset_item_id = %s
                    """,
                    (next_status, _value(row, "asset_item_id", 0)),
                )
                cursor.execute(
                    """
                    INSERT INTO platform_data_asset_reviews(
                        tenant_id, asset_version_id, decision, reviewer_user_id,
                        comments, decided_at, created_by
                    ) VALUES (%s, %s, %s, %s, %s, now(), %s)
                    """,
                    (
                        tenant_key, _value(row, "asset_version_id", 2), decision,
                        reviewer_key, str(comments or "")[:2000], reviewer_key,
                    ),
                )
        reviewed = self.get_item(tenant_id, item_type, item_id)
        if reviewed is None:
            raise RuntimeError("data_asset_review_persistence_failed")
        return reviewed

    def delete_item(self, tenant_id: str, item_type: str, item_id: str) -> bool:
        _require_valid_type(item_type)
        _require_deletable_asset(item_type, item_id)
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_data_asset_items
                    SET status = 'archived', updated_at = now(), lock_version = lock_version + 1
                    WHERE tenant_id = %s AND item_type = %s AND item_code = %s AND status <> 'archived'
                    RETURNING asset_item_id, payload
                    """,
                    (tenant_key, item_type, item_id),
                )
                row = cursor.fetchone()
                if row:
                    cursor.execute(
                        "UPDATE platform_data_asset_versions SET status = 'archived', updated_at = now() WHERE asset_item_id = %s AND status = 'active'",
                        (_value(row, "asset_item_id", 0),),
                    )
                    if item_type == "topic_table":
                        payload = _value(row, "payload", 1)
                        if isinstance(payload, str):
                            payload = json.loads(payload)
                        topic_code = str((payload or {}).get("code") or item_id).strip()
                        cursor.execute(
                            """
                            UPDATE platform_topic_tables
                            SET status = 'archived', updated_at = now(), lock_version = lock_version + 1
                            WHERE tenant_id = %s AND topic_code = %s AND status <> 'archived'
                            """,
                            (tenant_key, topic_code),
                        )
                return row is not None

    @staticmethod
    def _publish_topic_table(
        connection: Any,
        *,
        tenant_key: Any,
        actor_key: Any,
        payload: dict[str, Any],
        version_number: int,
    ) -> None:
        """Synchronize the reviewed UI asset into the normalized execution catalog."""

        topic_code = str(payload.get("code") or payload.get("id") or "").strip()
        query_template = str(payload.get("sql") or "").strip()
        query_hash = hashlib.sha256(query_template.encode("utf-8")).hexdigest()
        freshness = payload.get("freshnessSlaSeconds")
        freshness_seconds = int(freshness) if str(freshness or "").strip() else None
        if freshness_seconds is not None and freshness_seconds <= 0:
            raise ValueError("topic_table_freshness_sla_invalid")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO platform_topic_tables(
                    tenant_id, topic_code, topic_name, description, current_version_no,
                    query_template, query_hash, freshness_sla_seconds, status,
                    validated_at, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'published', now(), %s)
                ON CONFLICT (tenant_id, topic_code) DO UPDATE SET
                    topic_name = EXCLUDED.topic_name,
                    description = EXCLUDED.description,
                    current_version_no = EXCLUDED.current_version_no,
                    query_template = EXCLUDED.query_template,
                    query_hash = EXCLUDED.query_hash,
                    freshness_sla_seconds = EXCLUDED.freshness_sla_seconds,
                    status = 'published', validated_at = now(), updated_at = now(),
                    lock_version = platform_topic_tables.lock_version + 1
                RETURNING topic_table_id
                """,
                (
                    tenant_key,
                    topic_code,
                    str(payload.get("name") or topic_code).strip(),
                    str(payload.get("description") or "").strip(),
                    int(version_number),
                    query_template,
                    query_hash,
                    freshness_seconds,
                    actor_key,
                ),
            )
            topic_id = _value(cursor.fetchone(), "topic_table_id", 0)
            cursor.execute("DELETE FROM platform_topic_table_fields WHERE topic_table_id = %s", (topic_id,))
            for position, field in enumerate(payload.get("fields") or (), start=1):
                field_code = str(field.get("fieldNameEn") or "").strip()
                is_measure = bool(field.get("isMetric"))
                cursor.execute(
                    """
                    INSERT INTO platform_topic_table_fields(
                        tenant_id, topic_table_id, field_code, field_name, data_type,
                        ordinal_position, source_expression, is_dimension, is_measure, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        tenant_key,
                        topic_id,
                        field_code,
                        str(field.get("fieldNameCn") or field_code).strip(),
                        str(field.get("type") or "string").strip(),
                        position,
                        str(field.get("sourceExpression") or field_code).strip(),
                        not is_measure,
                        is_measure,
                        actor_key,
                    ),
                )

    def _bundle(self, tenant_id: str, *, published: bool) -> dict[str, list[dict[str, Any]]]:
        mapping = {output_key: item_type for item_type, output_key in ASSET_BUNDLE_KEYS.items()}
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            result = {}
            for output_key, item_type in mapping.items():
                rows = self._rows(
                    connection,
                    "i.tenant_id = %s AND i.item_type = %s" + (" AND v.status = 'active'" if published else " AND i.status <> 'archived'"),
                    (tenant_key, item_type),
                    published=published,
                )
                result[output_key] = visible_items_for_tenant(
                    tenant_id,
                    item_type,
                    sorted((self._asset_from_row(item_type, row) for row in rows), key=_sort_key),
                )
        return result

    @staticmethod
    def _rows(connection: Any, where: str, params: tuple[Any, ...], *, published: bool) -> list[Any]:
        version_join = (
            "JOIN platform_data_asset_versions v ON v.asset_item_id = i.asset_item_id"
            if published
            else """
                JOIN (
                    SELECT ranked.*
                    FROM (
                        SELECT x.*, ROW_NUMBER() OVER (
                            PARTITION BY x.asset_item_id ORDER BY x.version_number DESC
                        ) AS latest_rank
                        FROM platform_data_asset_versions x
                    ) ranked
                    WHERE ranked.latest_rank = 1
                ) v ON v.asset_item_id = i.asset_item_id
            """
        )
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT i.payload, v.status AS lifecycle_status, v.version_number,
                       v.schema_version, i.lock_version, submitter.external_subject AS submitted_by,
                       reviewer.external_subject AS reviewed_by, v.reviewed_at,
                       CASE WHEN v.status = 'active' THEN v.reviewed_at END AS published_at
                FROM platform_data_asset_items i
                {version_join}
                LEFT JOIN platform_user_profiles submitter ON submitter.user_id = v.submitted_by
                LEFT JOIN platform_user_profiles reviewer ON reviewer.user_id = v.reviewed_by
                WHERE {where}
                ORDER BY i.updated_at DESC, i.item_code
                LIMIT 200
                """,
                params,
            )
            return list(cursor.fetchall())

    @staticmethod
    def _asset_from_row(item_type: str, row: Any) -> dict[str, Any]:
        payload = _value(row, "payload", 0)
        if isinstance(payload, str):
            payload = json.loads(payload)
        normalized = _normalize_asset_payload_for_read(item_type, dict(payload))
        return _governed_asset_payload(
            normalized,
            status=str(_value(row, "lifecycle_status", 1)),
            version_number=int(_value(row, "version_number", 2)),
            submitted_by=str(_value(row, "submitted_by", 5) or ""),
            lock_version=int(_value(row, "lock_version", 4)),
            reviewed_by=str(_value(row, "reviewed_by", 6) or ""),
            reviewed_at=_iso(_value(row, "reviewed_at", 7)),
            published_at=_iso(_value(row, "published_at", 8)),
        )

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self.pool.connection() as connection:
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise


def _now_text() -> str:
    return datetime.now().astimezone().isoformat()


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value or "")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]
