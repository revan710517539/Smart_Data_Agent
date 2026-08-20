from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from backend.platform.storage import connect_sqlite
from typing import Any

from .semantics import validate_metric_dictionary_semantics


METRIC_STRING_FIELDS = (
    "metricId",
    "metricName",
    "definition",
    "valueLogic",
    "sourceTable",
    "dimension",
    "description",
    "applicationScene",
    "systemSource",
    "statTime",
    "referenceDocument",
    "createdBy",
    "tenantId",
    "metricCode",
    "datasetId",
    "aggregationType",
    "numeratorField",
    "denominatorField",
    "unit",
    "grain",
    "semanticStatus",
    "semanticVersion",
)
METRIC_LIST_FIELDS = (
    "visibleInstitutions",
    "visibleRoles",
)


class InMemoryMetricDictionaryStore:
    def __init__(self) -> None:
        self._metrics_by_tenant: dict[str, dict[str, dict[str, Any]]] = {}

    def list(self, tenant_id: str) -> list[dict[str, Any]]:
        metrics = self._metrics_by_tenant.get(tenant_id, {})
        return sorted(metrics.values(), key=lambda metric: metric.get("metricId", ""))

    def list_all(self) -> list[dict[str, Any]]:
        return sorted(
            [metric for metrics in self._metrics_by_tenant.values() for metric in metrics.values()],
            key=lambda metric: (metric.get("tenantId", ""), metric.get("metricId", "")),
        )

    def list_visible(
        self,
        tenant_id: str,
        role_names: set[str],
        user_id: str,
        is_super_admin: bool = False,
    ) -> list[dict[str, Any]]:
        if is_super_admin:
            return self.list_all()
        return sorted(
            [
                metric
                for metric in self.list_all()
                if _metric_visible(metric, tenant_id, role_names, user_id)
            ],
            key=lambda metric: (metric.get("tenantId", ""), metric.get("metricId", "")),
        )

    def get(self, tenant_id: str, metric_id: str) -> dict[str, Any] | None:
        return self._metrics_by_tenant.get(tenant_id, {}).get(metric_id)

    def replace_all(self, tenant_id: str, metrics: list[dict[str, Any]], updated_by: str | None = None) -> list[dict[str, Any]]:
        normalized = [_normalize_metric(metric) for metric in metrics]
        _assert_unique_metric_names(normalized)
        for metric in normalized:
            metric["createdBy"] = str(metric.get("createdBy") or updated_by or "")
            metric["tenantId"] = tenant_id
        self._metrics_by_tenant[tenant_id] = {metric["metricId"]: metric for metric in normalized}
        return self.list(tenant_id)

    def upsert(self, tenant_id: str, metric: dict[str, Any], updated_by: str | None = None) -> dict[str, Any]:
        return self.upsert_many(tenant_id, [metric], updated_by=updated_by)[0]

    def upsert_many(self, tenant_id: str, metrics: list[dict[str, Any]], updated_by: str | None = None) -> list[dict[str, Any]]:
        if not metrics:
            return []
        working = dict(self._metrics_by_tenant.get(tenant_id, {}))
        saved: list[dict[str, Any]] = []
        for metric in metrics:
            normalized = _normalize_metric(metric)
            _assert_metric_name_available(working.values(), normalized["metricName"], normalized["metricId"])
            existing = working.get(normalized["metricId"])
            normalized["createdBy"] = existing.get("createdBy") if existing else str(updated_by or normalized.get("createdBy") or "")
            normalized["tenantId"] = tenant_id
            working[normalized["metricId"]] = normalized
            saved.append(normalized)
        self._metrics_by_tenant[tenant_id] = working
        return saved

    def delete(self, tenant_id: str, metric_id: str) -> bool:
        metrics = self._metrics_by_tenant.setdefault(tenant_id, {})
        return metrics.pop(metric_id, None) is not None


class SQLiteMetricDictionaryStore:
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
            CREATE TABLE IF NOT EXISTS platform_metric_dictionary (
                tenant_id TEXT NOT NULL,
                metric_id TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                created_by TEXT,
                updated_by TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, metric_id)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_metric_dictionary_name
                ON platform_metric_dictionary(tenant_id, metric_name);
            CREATE INDEX IF NOT EXISTS idx_platform_metric_dictionary_tenant
                ON platform_metric_dictionary(tenant_id);

            CREATE TABLE IF NOT EXISTS platform_metric_visibility (
                owner_tenant_id TEXT NOT NULL,
                metric_id TEXT NOT NULL,
                visible_tenant_id TEXT NOT NULL,
                visible_role_name TEXT NOT NULL DEFAULT '*',
                PRIMARY KEY (owner_tenant_id, metric_id, visible_tenant_id, visible_role_name),
                FOREIGN KEY (owner_tenant_id, metric_id)
                    REFERENCES platform_metric_dictionary(tenant_id, metric_id)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_platform_metric_visibility_lookup
                ON platform_metric_visibility(visible_tenant_id, visible_role_name);
            """
        )
        self._conn.commit()
        self._backfill_visibility_rows()

    def list(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT tenant_id, payload
            FROM platform_metric_dictionary
            WHERE tenant_id = ?
            ORDER BY metric_id
            """,
            (tenant_id,),
        ).fetchall()
        return [_payload_from_row(row) for row in rows]

    def list_all(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT tenant_id, payload
            FROM platform_metric_dictionary
            ORDER BY tenant_id, metric_id
            """
        ).fetchall()
        return [_payload_from_row(row) for row in rows]

    def list_visible(
        self,
        tenant_id: str,
        role_names: set[str],
        user_id: str,
        is_super_admin: bool = False,
    ) -> list[dict[str, Any]]:
        if is_super_admin:
            return self.list_all()
        role_values = sorted(role_names)
        role_placeholders = ",".join("?" for _ in role_values)
        role_match_sql = "v.visible_role_name = '*'"
        params: list[str] = [tenant_id, user_id, tenant_id, "*"]
        if role_values:
            role_match_sql = f"({role_match_sql} OR v.visible_role_name IN ({role_placeholders}))"
            params.extend(role_values)
        rows = self._conn.execute(
            f"""
            SELECT DISTINCT d.tenant_id, d.payload
            FROM platform_metric_dictionary d
            LEFT JOIN platform_metric_visibility v
                ON v.owner_tenant_id = d.tenant_id
               AND v.metric_id = d.metric_id
            WHERE (d.tenant_id = ? AND json_extract(d.payload, '$.createdBy') = ?)
               OR (
                    v.visible_tenant_id IN (?, ?)
                    AND {role_match_sql}
               )
            ORDER BY d.tenant_id, d.metric_id
            """,
            tuple(params),
        ).fetchall()
        return [_payload_from_row(row) for row in rows]

    def get(self, tenant_id: str, metric_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT tenant_id, payload, created_by
            FROM platform_metric_dictionary
            WHERE tenant_id = ? AND metric_id = ?
            """,
            (tenant_id, metric_id),
        ).fetchone()
        if row is None:
            return None
        payload = _payload_from_row(row)
        payload["createdBy"] = payload.get("createdBy") or row["created_by"] or ""
        return payload

    def replace_all(self, tenant_id: str, metrics: list[dict[str, Any]], updated_by: str | None = None) -> list[dict[str, Any]]:
        normalized = [_normalize_metric(metric) for metric in metrics]
        _assert_unique_metric_names(normalized)
        for metric in normalized:
            metric["createdBy"] = str(metric.get("createdBy") or updated_by or "")
            metric["tenantId"] = tenant_id
        with self._conn:
            self._conn.execute("DELETE FROM platform_metric_dictionary WHERE tenant_id = ?", (tenant_id,))
            self._conn.executemany(
                """
                INSERT INTO platform_metric_dictionary(
                    tenant_id, metric_id, metric_name, payload, created_by, updated_by, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [
                    (
                        tenant_id,
                        metric["metricId"],
                        metric["metricName"],
                        json.dumps(metric, ensure_ascii=False, sort_keys=True),
                        updated_by,
                        updated_by,
                    )
                    for metric in normalized
                ],
            )
            self._replace_visibility_rows(tenant_id, normalized)
        return self.list(tenant_id)

    def upsert(self, tenant_id: str, metric: dict[str, Any], updated_by: str | None = None) -> dict[str, Any]:
        return self.upsert_many(tenant_id, [metric], updated_by=updated_by)[0]

    def upsert_many(self, tenant_id: str, metrics: list[dict[str, Any]], updated_by: str | None = None) -> list[dict[str, Any]]:
        if not metrics:
            return []
        prepared: list[dict[str, Any]] = []
        for metric in metrics:
            normalized = _normalize_metric(metric)
            existing_metric = self.get(tenant_id, normalized["metricId"])
            normalized["createdBy"] = existing_metric.get("createdBy") if existing_metric else str(updated_by or normalized.get("createdBy") or "")
            normalized["tenantId"] = tenant_id
            existing = self._conn.execute(
                """
                SELECT metric_id
                FROM platform_metric_dictionary
                WHERE tenant_id = ? AND metric_name = ? AND metric_id <> ?
                """,
                (tenant_id, normalized["metricName"], normalized["metricId"]),
            ).fetchone()
            if existing:
                raise ValueError("指标已存在，请检查……")
            prepared.append(normalized)
        _assert_unique_metric_names(prepared)
        with self._conn:
            for normalized in prepared:
                self._conn.execute(
                    """
                    INSERT INTO platform_metric_dictionary(
                        tenant_id, metric_id, metric_name, payload, created_by, updated_by, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(tenant_id, metric_id) DO UPDATE SET
                        metric_name = excluded.metric_name,
                        payload = excluded.payload,
                        updated_by = excluded.updated_by,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        tenant_id,
                        normalized["metricId"],
                        normalized["metricName"],
                        json.dumps(normalized, ensure_ascii=False, sort_keys=True),
                        normalized["createdBy"] or updated_by,
                        updated_by,
                    ),
                )
            self._replace_visibility_rows(tenant_id, prepared, metric_ids={item["metricId"] for item in prepared})
        return prepared

    def delete(self, tenant_id: str, metric_id: str) -> bool:
        with self._conn:
            self._conn.execute(
                "DELETE FROM platform_metric_visibility WHERE owner_tenant_id = ? AND metric_id = ?",
                (tenant_id, metric_id),
            )
            cursor = self._conn.execute(
                """
                DELETE FROM platform_metric_dictionary
                WHERE tenant_id = ? AND metric_id = ?
                """,
                (tenant_id, metric_id),
            )
        return cursor.rowcount > 0

    def _replace_visibility_rows(
        self,
        tenant_id: str,
        metrics: list[dict[str, Any]],
        metric_ids: set[str] | None = None,
    ) -> None:
        if metric_ids is None:
            self._conn.execute("DELETE FROM platform_metric_visibility WHERE owner_tenant_id = ?", (tenant_id,))
        else:
            self._conn.executemany(
                "DELETE FROM platform_metric_visibility WHERE owner_tenant_id = ? AND metric_id = ?",
                [(tenant_id, metric_id) for metric_id in metric_ids],
            )
        rows = [
            row
            for metric in metrics
            for row in _visibility_rows(tenant_id, metric)
        ]
        if rows:
            self._conn.executemany(
                """
                INSERT OR IGNORE INTO platform_metric_visibility(
                    owner_tenant_id, metric_id, visible_tenant_id, visible_role_name
                )
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )

    def _backfill_visibility_rows(self) -> None:
        count = self._conn.execute("SELECT COUNT(*) FROM platform_metric_visibility").fetchone()[0]
        if count:
            return
        rows = self._conn.execute(
            "SELECT tenant_id, payload FROM platform_metric_dictionary ORDER BY tenant_id, metric_id"
        ).fetchall()
        with self._conn:
            for row in rows:
                metric = _payload_from_row(row)
                self._replace_visibility_rows(row["tenant_id"], [metric], metric_ids={metric["metricId"]})


def _normalize_metric(metric: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {field: str(metric.get(field) or "").strip() for field in METRIC_STRING_FIELDS}
    for field in METRIC_LIST_FIELDS:
        normalized[field] = _normalize_string_list(metric.get(field))
    if not normalized["metricId"] or not normalized["metricName"]:
        raise ValueError("请至少填写指标ID和指标名称。")
    normalized["semanticStatus"] = normalized["semanticStatus"].lower() or "documentation"
    raw_multiplier = metric.get("multiplier", 1)
    try:
        normalized["multiplier"] = float(1 if raw_multiplier in (None, "") else raw_multiplier)
    except (TypeError, ValueError) as exc:
        raise ValueError("metric_semantic_multiplier_invalid") from exc
    validate_metric_dictionary_semantics(normalized)
    return normalized


def _assert_unique_metric_names(metrics: list[dict[str, Any]]) -> None:
    names: set[str] = set()
    for metric in metrics:
        name = metric["metricName"]
        if name in names:
            raise ValueError("指标已存在，请检查……")
        names.add(name)


def _assert_metric_name_available(metrics: Any, metric_name: str, metric_id: str) -> None:
    for metric in metrics:
        if metric.get("metricName") == metric_name and metric.get("metricId") != metric_id:
            raise ValueError("指标已存在，请检查……")


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _payload_from_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(row["payload"])
    payload["tenantId"] = payload.get("tenantId") or row["tenant_id"]
    payload["visibleInstitutions"] = _normalize_string_list(payload.get("visibleInstitutions"))
    payload["visibleRoles"] = _normalize_string_list(payload.get("visibleRoles"))
    return payload


def _metric_visible(metric: dict[str, Any], tenant_id: str, role_names: set[str], user_id: str) -> bool:
    metric_tenant_id = str(metric.get("tenantId") or "")
    created_by = str(metric.get("createdBy") or "").strip()
    if created_by and created_by == user_id and metric_tenant_id == tenant_id:
        return True
    visible_institutions = _normalize_string_list(metric.get("visibleInstitutions"))
    visible_roles = _normalize_string_list(metric.get("visibleRoles"))
    tenant_label = tenant_id.removeprefix("tenant:")
    institution_visible = tenant_label in visible_institutions or "全部机构" in visible_institutions
    role_visible = bool(role_names & set(visible_roles))
    if visible_institutions and visible_roles:
        return institution_visible and role_visible
    if visible_institutions:
        return institution_visible
    if visible_roles:
        return metric_tenant_id == tenant_id and role_visible
    return False


def _visibility_rows(tenant_id: str, metric: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    metric_id = str(metric.get("metricId") or "").strip()
    if not metric_id:
        return []
    visible_institutions = _normalize_string_list(metric.get("visibleInstitutions"))
    visible_roles = _normalize_string_list(metric.get("visibleRoles"))
    visible_tenant_ids = [_visible_tenant_id(value, tenant_id) for value in visible_institutions]
    rows: list[tuple[str, str, str, str]] = []
    if visible_tenant_ids and visible_roles:
        for visible_tenant_id in visible_tenant_ids:
            for role_name in visible_roles:
                rows.append((tenant_id, metric_id, visible_tenant_id, role_name))
    elif visible_tenant_ids:
        for visible_tenant_id in visible_tenant_ids:
            rows.append((tenant_id, metric_id, visible_tenant_id, "*"))
    elif visible_roles:
        for role_name in visible_roles:
            rows.append((tenant_id, metric_id, tenant_id, role_name))
    return rows


def _visible_tenant_id(value: str, owner_tenant_id: str) -> str:
    if value == "全部机构":
        return "*"
    if value.startswith("tenant:"):
        return value
    if not value:
        return owner_tenant_id
    return f"tenant:{value}"
