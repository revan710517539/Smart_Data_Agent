from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from typing import Any, Iterator

from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.postgresql import PostgreSQLConnectionPool

from .store import _assert_unique_metric_names, _metric_visible, _normalize_metric


class PostgreSQLMetricDictionaryStore:
    """Governed production metric dictionary with immutable executable versions."""

    def __init__(self, pool: PostgreSQLConnectionPool, *, owns_pool: bool = False) -> None:
        self.pool = pool
        self.owns_pool = owns_pool

    def close(self) -> None:
        if self.owns_pool:
            self.pool.close()

    def list(self, tenant_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            return self._list_where(connection, "d.tenant_id = %s AND d.status <> 'disabled'", (tenant_key,))

    def list_all(self) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            return self._list_where(connection, "d.status <> 'disabled'", ())

    def list_visible(
        self,
        tenant_id: str,
        role_names: set[str],
        user_id: str,
        is_super_admin: bool = False,
    ) -> list[dict[str, Any]]:
        items = self.list_all()
        if is_super_admin:
            return items
        return [item for item in items if _metric_visible(item, tenant_id, role_names, user_id)]

    def get(self, tenant_id: str, metric_id: str) -> dict[str, Any] | None:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            rows = self._list_where(
                connection,
                "d.tenant_id = %s AND d.metric_key = %s AND d.status <> 'disabled'",
                (tenant_key, metric_id),
            )
        return rows[0] if rows else None

    def replace_all(self, tenant_id: str, metrics: list[dict[str, Any]], updated_by: str | None = None) -> list[dict[str, Any]]:
        normalized = [_normalize_metric(metric) for metric in metrics]
        _assert_unique_metric_names(normalized)
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE platform_metric_dictionary SET status = 'disabled', updated_at = now(), lock_version = lock_version + 1 WHERE tenant_id = %s",
                    (tenant_key,),
                )
            for metric in normalized:
                self._upsert(connection, tenant_id, tenant_key, metric, updated_by)
        return self.list(tenant_id)

    def upsert(self, tenant_id: str, metric: dict[str, Any], updated_by: str | None = None) -> dict[str, Any]:
        normalized = _normalize_metric(metric)
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            self._upsert(connection, tenant_id, tenant_key, normalized, updated_by)
        return self.get(tenant_id, normalized["metricId"]) or normalized

    def delete(self, tenant_id: str, metric_id: str) -> bool:
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_metric_dictionary
                    SET status = 'disabled', updated_at = now(), lock_version = lock_version + 1
                    WHERE tenant_id = %s AND metric_key = %s AND status <> 'disabled'
                    RETURNING metric_id
                    """,
                    (tenant_key, metric_id),
                )
                row = cursor.fetchone()
                if row:
                    cursor.execute("DELETE FROM platform_metric_visibility WHERE metric_id = %s", (_value(row, "metric_id", 0),))
                return row is not None

    def _upsert(
        self,
        connection: Any,
        tenant_id: str,
        tenant_key: Any,
        metric: dict[str, Any],
        updated_by: str | None,
    ) -> None:
        actor_key = PostgreSQLIdentityResolver.user_id(connection, updated_by, required=False) if updated_by else None
        metric_key = str(metric["metricId"])
        metric_code = str(metric.get("metricCode") or metric_key)
        semantic_status = str(metric.get("semanticStatus") or "documentation").lower()
        dictionary_status = {
            "documentation": "draft",
            "draft": "draft",
            "published": "published",
            "deprecated": "deprecated",
        }[semantic_status]
        version_no = _version_no(metric.get("semanticVersion")) if _has_executable_semantics(metric) else 0
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT metric_id, metric_name, metadata, owner_user_id
                FROM platform_metric_dictionary
                WHERE tenant_id = %s AND metric_key = %s
                """,
                (tenant_key, metric_key),
            )
            existing = cursor.fetchone()
            cursor.execute(
                """
                SELECT metric_key FROM platform_metric_dictionary
                WHERE tenant_id = %s AND metric_name = %s AND metric_key <> %s AND status <> 'disabled'
                """,
                (tenant_key, metric["metricName"], metric_key),
            )
            if cursor.fetchone():
                raise ValueError("指标已存在，请检查……")
        existing_metadata = _json_value(_value(existing, "metadata", 2), {}) if existing else {}
        created_by_code = str(existing_metadata.get("createdBy") or metric.get("createdBy") or updated_by or "")
        owner_key = (
            PostgreSQLIdentityResolver.user_id(connection, created_by_code, required=False)
            if created_by_code else actor_key
        )
        payload = {**metric, "createdBy": created_by_code, "tenantId": tenant_id}
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO platform_metric_dictionary(
                    tenant_id, metric_key, metric_code, metric_name, metric_domain, unit,
                    current_version_no, status, owner_user_id, metadata, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                ON CONFLICT (tenant_id, metric_key) DO UPDATE SET
                    metric_code = EXCLUDED.metric_code, metric_name = EXCLUDED.metric_name,
                    metric_domain = EXCLUDED.metric_domain, unit = EXCLUDED.unit,
                    current_version_no = EXCLUDED.current_version_no, status = EXCLUDED.status,
                    owner_user_id = COALESCE(platform_metric_dictionary.owner_user_id, EXCLUDED.owner_user_id),
                    metadata = EXCLUDED.metadata, updated_at = now(),
                    lock_version = platform_metric_dictionary.lock_version + 1
                RETURNING metric_id
                """,
                (
                    tenant_key, metric_key, metric_code, metric["metricName"],
                    str(metric.get("systemSource") or "general")[:120],
                    str(metric.get("unit") or "count")[:64],
                    version_no if semantic_status == "published" else 0,
                    dictionary_status, owner_key, _json(payload), actor_key,
                ),
            )
            internal_metric_id = _value(cursor.fetchone(), "metric_id", 0)
        if version_no:
            self._upsert_version(
                connection, tenant_key, internal_metric_id, metric, version_no,
                "published" if semantic_status == "published" else "superseded" if semantic_status == "deprecated" else "draft",
                actor_key,
            )
        self._replace_visibility(connection, tenant_key, internal_metric_id, metric, actor_key)

    def _upsert_version(
        self,
        connection: Any,
        tenant_key: Any,
        metric_id: Any,
        metric: dict[str, Any],
        version_no: int,
        status: str,
        actor_key: Any,
    ) -> None:
        dataset_code = str(metric.get("datasetId") or "")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT dataset_id FROM platform_datasets WHERE tenant_id = %s AND dataset_code = %s AND status = 'active'",
                (tenant_key, dataset_code),
            )
            dataset = cursor.fetchone()
            if not dataset:
                raise KeyError("metric_source_dataset_not_active")
            dataset_id = _value(dataset, "dataset_id", 0)
            definition = str(metric.get("definition") or metric.get("description") or metric["metricName"])
            aggregation = str(metric.get("aggregationType") or "").lower()
            numerator = str(metric.get("numeratorField") or "") or None
            denominator = str(metric.get("denominatorField") or "") or None
            value_expression = (
                f"ratio({numerator},{denominator})" if aggregation == "ratio"
                else str(metric.get("metricCode") or metric["metricId"])
            )
            grain = _split_labels(metric.get("grain"))
            dimensions = _split_labels(metric.get("dimension"))
            version_payload = {
                "definition": definition,
                "aggregation": aggregation,
                "value_expression": value_expression,
                "numerator": numerator,
                "denominator": denominator,
                "multiplier": metric.get("multiplier", 1),
                "grain": grain,
                "dataset_id": dataset_code,
                "dimensions": dimensions,
                "status": status,
            }
            checksum = hashlib.sha256(_json(version_payload).encode("utf-8")).hexdigest()
            cursor.execute(
                "SELECT checksum FROM platform_metric_versions WHERE metric_id = %s AND version_no = %s",
                (metric_id, version_no),
            )
            existing = cursor.fetchone()
            if existing:
                if str(_value(existing, "checksum", 0)) != checksum:
                    raise ValueError("metric_version_checksum_drift")
                return
            if status == "published":
                cursor.execute(
                    "UPDATE platform_metric_versions SET status = 'superseded', effective_to = now(), updated_at = now() WHERE metric_id = %s AND status = 'published'",
                    (metric_id,),
                )
            cursor.execute(
                """
                INSERT INTO platform_metric_versions(
                    tenant_id, metric_id, version_no, definition, aggregation_type,
                    value_expression, numerator_expression, denominator_expression,
                    multiplier, default_grain, source_dataset_id, allowed_dimensions,
                    effective_from, status, checksum, created_by
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s::jsonb, %s, %s::jsonb, now(), %s, %s, %s
                )
                """,
                (
                    tenant_key, metric_id, version_no, definition, aggregation,
                    value_expression, numerator, denominator, float(metric.get("multiplier", 1)),
                    _json(grain), dataset_id, _json(dimensions), status, checksum, actor_key,
                ),
            )

    @staticmethod
    def _replace_visibility(
        connection: Any,
        owner_tenant_key: Any,
        metric_id: Any,
        metric: dict[str, Any],
        actor_key: Any,
    ) -> None:
        institutions = list(metric.get("visibleInstitutions") or [])
        role_names = list(metric.get("visibleRoles") or [])
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM platform_metric_visibility WHERE metric_id = %s", (metric_id,))
            if "全部机构" in institutions:
                cursor.execute("SELECT tenant_id FROM platform_tenants WHERE status = 'active'")
                tenant_keys = [_value(row, "tenant_id", 0) for row in cursor.fetchall()]
            elif institutions:
                tenant_keys = []
                for label in institutions:
                    code = str(label) if str(label).startswith("tenant:") else f"tenant:{label}"
                    tenant_id = PostgreSQLIdentityResolver.tenant_id(connection, code, required=False)
                    if tenant_id is not None:
                        tenant_keys.append(tenant_id)
            else:
                tenant_keys = [owner_tenant_key]
            subjects: set[tuple[str, Any]] = set()
            if role_names:
                for tenant_key in tenant_keys:
                    cursor.execute(
                        """
                        SELECT role_id FROM auth_roles
                        WHERE tenant_id = %s AND role_name = ANY(%s) AND status = 'active'
                        """,
                        (tenant_key, role_names),
                    )
                    subjects.update(("role", _value(row, "role_id", 0)) for row in cursor.fetchall())
            elif institutions:
                subjects.update(("tenant", tenant_key) for tenant_key in tenant_keys)
            for subject_type, subject_id in subjects:
                cursor.execute(
                    """
                    INSERT INTO platform_metric_visibility(
                        tenant_id, metric_id, subject_type, subject_id, effect, created_by
                    ) VALUES (%s, %s, %s, %s, 'allow', %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (owner_tenant_key, metric_id, subject_type, subject_id, actor_key),
                )

    @staticmethod
    def _list_where(connection: Any, where: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT d.metadata, t.tenant_code, d.metric_key, d.metric_name,
                       d.metric_code, d.status, owner.external_subject AS owner_code
                FROM platform_metric_dictionary d
                JOIN platform_tenants t ON t.tenant_id = d.tenant_id
                LEFT JOIN platform_user_profiles owner ON owner.user_id = d.owner_user_id
                WHERE {where}
                ORDER BY t.tenant_code, d.metric_key
                """,
                params,
            )
            rows = cursor.fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            payload = dict(_json_value(_value(row, "metadata", 0), {}))
            payload["tenantId"] = str(_value(row, "tenant_code", 1))
            payload["metricId"] = str(_value(row, "metric_key", 2))
            payload["metricName"] = str(_value(row, "metric_name", 3))
            payload["metricCode"] = str(payload.get("metricCode") or _value(row, "metric_code", 4))
            payload["createdBy"] = str(payload.get("createdBy") or _value(row, "owner_code", 6) or "")
            payload["visibleInstitutions"] = list(payload.get("visibleInstitutions") or [])
            payload["visibleRoles"] = list(payload.get("visibleRoles") or [])
            items.append(payload)
        return items

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self.pool.connection() as connection:
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise


def _has_executable_semantics(metric: dict[str, Any]) -> bool:
    return bool(metric.get("metricCode") and metric.get("datasetId") and metric.get("aggregationType") and metric.get("semanticVersion"))


def _version_no(value: Any) -> int:
    match = re.search(r"(\d+)", str(value or ""))
    if not match or int(match.group(1)) < 1:
        raise ValueError("metric_semantic_version_invalid")
    return int(match.group(1))


def _split_labels(value: Any) -> list[str]:
    if isinstance(value, list):
        parts = value
    else:
        parts = re.split(r"[,，、]", str(value or ""))
    return [str(item).strip() for item in parts if str(item).strip()]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value) if isinstance(value, str) else value


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]
