from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from difflib import ndiff
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from backend.platform.database.mysql import MySQLConnectionPool
from backend.platform.metrics.semantics import validate_metric_dictionary_semantics


class MetricVersionStore(Protocol):
    def list_versions(self, tenant_id: str, metric_key: str) -> list[dict[str, Any]]: ...
    def create_draft(self, tenant_id: str, metric_key: str, actor_user_id: str, definition: dict[str, Any], parent_version_id: str | None = None) -> dict[str, Any]: ...
    def transition(self, tenant_id: str, version_id: str, actor_user_id: str, action: str, comment: str = "") -> dict[str, Any]: ...
    def impact(self, tenant_id: str, metric_key: str) -> dict[str, Any]: ...


class MetricVersionService:
    def __init__(self, store: MetricVersionStore) -> None:
        self.store = store

    def list(self, tenant_id: str, metric_key: str) -> list[dict[str, Any]]:
        return self.store.list_versions(tenant_id, _required(metric_key, "metric_key"))

    def create(self, tenant_id: str, metric_key: str, actor_user_id: str, definition: dict[str, Any], parent_version_id: str | None = None) -> dict[str, Any]:
        normalized = dict(definition)
        normalized.setdefault("metricId", metric_key)
        normalized.setdefault("semanticStatus", "draft")
        normalized.setdefault("semanticVersion", "v1")
        validate_metric_dictionary_semantics(normalized)
        return self.store.create_draft(tenant_id, _required(metric_key, "metric_key"), actor_user_id, normalized, parent_version_id)

    def review(self, tenant_id: str, version_id: str, actor_user_id: str, action: str, comment: str = "") -> dict[str, Any]:
        if action not in {"submit", "publish", "reject", "archive"}:
            raise ValueError("metric_version_action_invalid")
        return self.store.transition(tenant_id, _required(version_id, "version_id"), actor_user_id, action, comment[:2_000])

    def rollback(self, tenant_id: str, metric_key: str, version_id: str, actor_user_id: str) -> dict[str, Any]:
        versions = self.list(tenant_id, metric_key)
        source = next((item for item in versions if item["version_id"] == version_id), None)
        if source is None:
            raise KeyError("metric_version_not_found")
        draft = self.create(tenant_id, metric_key, actor_user_id, source["definition"], parent_version_id=version_id)
        return {**draft, "rollback_of": version_id}

    def diff(self, tenant_id: str, metric_key: str, left_id: str, right_id: str) -> dict[str, Any]:
        versions = {item["version_id"]: item for item in self.list(tenant_id, metric_key)}
        if left_id not in versions or right_id not in versions:
            raise KeyError("metric_version_not_found")
        left = versions[left_id]["definition"]
        right = versions[right_id]["definition"]
        changed = []
        for key in sorted(set(left) | set(right)):
            if left.get(key) != right.get(key):
                changed.append({"field": key, "before": left.get(key), "after": right.get(key)})
        return {"left_version_id": left_id, "right_version_id": right_id, "changed_fields": changed, "changed_count": len(changed)}

    def impact(self, tenant_id: str, metric_key: str) -> dict[str, Any]:
        return self.store.impact(tenant_id, _required(metric_key, "metric_key"))


class InMemoryMetricVersionStore:
    def __init__(self) -> None:
        self._versions: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._lock = RLock()

    def list_versions(self, tenant_id: str, metric_key: str) -> list[dict[str, Any]]:
        return deepcopy(sorted(self._versions.get((tenant_id, metric_key), []), key=lambda item: item["version_no"], reverse=True))

    def create_draft(self, tenant_id: str, metric_key: str, actor_user_id: str, definition: dict[str, Any], parent_version_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            versions = self._versions.setdefault((tenant_id, metric_key), [])
            version = {"version_id": f"mv_{uuid4().hex}", "metric_key": metric_key, "version_no": max([item["version_no"] for item in versions], default=0) + 1, "status": "draft", "definition": deepcopy(definition), "checksum": _hash(definition), "parent_version_id": parent_version_id, "created_by": actor_user_id, "submitted_by": None, "reviewed_by": None, "review_comment": "", "created_at": _now()}
            versions.append(version)
            return deepcopy(version)

    def transition(self, tenant_id: str, version_id: str, actor_user_id: str, action: str, comment: str = "") -> dict[str, Any]:
        with self._lock:
            version, versions = self._find(tenant_id, version_id)
            if action == "submit":
                if version["status"] != "draft":
                    raise ValueError("metric_version_submit_state_invalid")
                version.update(status="review", submitted_by=actor_user_id, submitted_at=_now())
            elif action in {"publish", "reject"}:
                if version["status"] != "review":
                    raise ValueError("metric_version_review_state_invalid")
                if version["submitted_by"] == actor_user_id:
                    raise PermissionError("metric_version_four_eyes_required")
                if action == "publish":
                    for current in versions:
                        if current["status"] == "published":
                            current["status"] = "superseded"
                            current["effective_to"] = _now()
                    version["status"] = "published"
                    version["effective_from"] = _now()
                else:
                    version["status"] = "rejected"
                version.update(reviewed_by=actor_user_id, reviewed_at=_now(), review_comment=comment)
            elif action == "archive":
                if version["status"] not in {"draft", "rejected", "superseded"}:
                    raise ValueError("metric_version_archive_state_invalid")
                version["status"] = "archived"
            return deepcopy(version)

    def impact(self, tenant_id: str, metric_key: str) -> dict[str, Any]:
        return {"metric_key": metric_key, "reports": [], "skills": [], "analysis_tasks": [], "cache_entries": [], "impact_count": 0}

    def _find(self, tenant_id: str, version_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        for (tenant, _), versions in self._versions.items():
            if tenant != tenant_id:
                continue
            for version in versions:
                if version["version_id"] == version_id:
                    return version, versions
        raise KeyError("metric_version_not_found")


class MySQLMetricVersionStore:
    def __init__(self, pool: MySQLConnectionPool) -> None:
        self.pool = pool

    def list_versions(self, tenant_id: str, metric_key: str) -> list[dict[str, Any]]:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            tenant_key, metric_id = _resolve_metric(cursor, tenant_id, metric_key)
            cursor.execute("SELECT metric_version_id,version_no,definition,aggregation_type,value_expression,numerator_expression,denominator_expression,multiplier,default_grain,allowed_dimensions,status,checksum,parent_version_id,submitted_by,submitted_at,reviewed_by,reviewed_at,review_comment,effective_from,effective_to,created_by,created_at FROM platform_metric_versions WHERE tenant_id=%s AND metric_id=%s ORDER BY version_no DESC", (tenant_key, metric_id))
            rows = cursor.fetchall()
        return [_version_row(row, metric_key) for row in rows]

    def create_draft(self, tenant_id: str, metric_key: str, actor_user_id: str, definition: dict[str, Any], parent_version_id: str | None = None) -> dict[str, Any]:
        with self.pool.transaction() as connection, connection.cursor() as cursor:
            tenant_key, metric_id = _resolve_metric(cursor, tenant_id, metric_key)
            actor_key = _resolve_user(cursor, actor_user_id)
            dataset_code = str(definition.get("datasetId") or "")
            cursor.execute("SELECT dataset_id FROM platform_datasets WHERE tenant_id=%s AND dataset_code=%s AND status='active'", (tenant_key, dataset_code))
            dataset = cursor.fetchone()
            if not dataset:
                raise KeyError("metric_source_dataset_not_active")
            cursor.execute("SELECT COALESCE(MAX(version_no),0)+1 AS version_no FROM platform_metric_versions WHERE metric_id=%s FOR UPDATE", (metric_id,))
            version_no = int(cursor.fetchone()["version_no"])
            version_id = str(uuid4())
            normalized = _normalized_definition(definition)
            checksum = _hash(normalized)
            cursor.execute("INSERT INTO platform_metric_versions(metric_version_id,tenant_id,metric_id,version_no,definition,aggregation_type,value_expression,numerator_expression,denominator_expression,multiplier,default_grain,source_dataset_id,allowed_dimensions,effective_from,status,checksum,parent_version_id,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6),'draft',%s,%s,%s)", (version_id, tenant_key, metric_id, version_no, normalized["definition"], normalized["aggregationType"], normalized["valueExpression"], normalized.get("numeratorField") or None, normalized.get("denominatorField") or None, normalized["multiplier"], _json(normalized["grain"]), str(dataset["dataset_id"]), _json(normalized["dimensions"]), checksum, parent_version_id, actor_key))
        return self.list_versions(tenant_id, metric_key)[0]

    def transition(self, tenant_id: str, version_id: str, actor_user_id: str, action: str, comment: str = "") -> dict[str, Any]:
        with self.pool.transaction() as connection, connection.cursor() as cursor:
            tenant_key = _resolve_tenant(cursor, tenant_id)
            actor_key = _resolve_user(cursor, actor_user_id)
            cursor.execute("SELECT metric_id,status,submitted_by FROM platform_metric_versions WHERE tenant_id=%s AND metric_version_id=%s FOR UPDATE", (tenant_key, version_id))
            row = cursor.fetchone()
            if not row:
                raise KeyError("metric_version_not_found")
            if action == "submit":
                if row["status"] != "draft":
                    raise ValueError("metric_version_submit_state_invalid")
                cursor.execute("UPDATE platform_metric_versions SET status='review',submitted_by=%s,submitted_at=UTC_TIMESTAMP(6),updated_at=UTC_TIMESTAMP(6),lock_version=lock_version+1 WHERE metric_version_id=%s", (actor_key, version_id))
            elif action in {"publish", "reject"}:
                if row["status"] != "review":
                    raise ValueError("metric_version_review_state_invalid")
                if str(row["submitted_by"]) == actor_key:
                    raise PermissionError("metric_version_four_eyes_required")
                if action == "publish":
                    cursor.execute("UPDATE platform_metric_versions SET status='superseded',effective_to=UTC_TIMESTAMP(6),updated_at=UTC_TIMESTAMP(6),lock_version=lock_version+1 WHERE metric_id=%s AND status='published'", (row["metric_id"],))
                    cursor.execute("UPDATE platform_metric_versions SET status='published',reviewed_by=%s,reviewed_at=UTC_TIMESTAMP(6),review_comment=%s,effective_from=UTC_TIMESTAMP(6),updated_at=UTC_TIMESTAMP(6),lock_version=lock_version+1 WHERE metric_version_id=%s", (actor_key, comment, version_id))
                    cursor.execute("UPDATE platform_metric_dictionary SET current_version_no=(SELECT version_no FROM platform_metric_versions WHERE metric_version_id=%s),status='published',updated_at=UTC_TIMESTAMP(6),lock_version=lock_version+1 WHERE metric_id=%s", (version_id, row["metric_id"]))
                else:
                    cursor.execute("UPDATE platform_metric_versions SET status='rejected',reviewed_by=%s,reviewed_at=UTC_TIMESTAMP(6),review_comment=%s,updated_at=UTC_TIMESTAMP(6),lock_version=lock_version+1 WHERE metric_version_id=%s", (actor_key, comment, version_id))
            elif action == "archive":
                if row["status"] not in {"draft", "rejected", "superseded"}:
                    raise ValueError("metric_version_archive_state_invalid")
                cursor.execute("UPDATE platform_metric_versions SET status='archived',updated_at=UTC_TIMESTAMP(6),lock_version=lock_version+1 WHERE metric_version_id=%s", (version_id,))
            cursor.execute("SELECT metric_key FROM platform_metric_dictionary WHERE metric_id=%s", (row["metric_id"],))
            metric_key = str(cursor.fetchone()["metric_key"])
        return next(item for item in self.list_versions(tenant_id, metric_key) if item["version_id"] == version_id)

    def impact(self, tenant_id: str, metric_key: str) -> dict[str, Any]:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            tenant_key, metric_id = _resolve_metric(cursor, tenant_id, metric_key)
            pattern = f'%"{metric_key}"%'
            queries = {
                "reports": ("SELECT report_key AS id FROM platform_reports WHERE tenant_id=%s AND CAST(metadata AS CHAR) LIKE %s LIMIT 100", (tenant_key, pattern)),
                "skills": ("SELECT skill_code AS id FROM platform_skills WHERE tenant_id=%s AND CAST(config AS CHAR) LIKE %s LIMIT 100", (tenant_key, pattern)),
                "analysis_tasks": ("SELECT request_id AS id FROM platform_analysis_tasks WHERE tenant_id=%s AND CAST(context_snapshot AS CHAR) LIKE %s LIMIT 100", (tenant_key, pattern)),
                "cache_entries": ("SELECT cache_key AS id FROM platform_analysis_result_cache WHERE tenant_id=%s AND semantic_version_hash<>'' AND invalidated_at IS NULL LIMIT 100", (tenant_key,)),
            }
            result: dict[str, list[str]] = {}
            for key, (sql, params) in queries.items():
                cursor.execute(sql, params)
                result[key] = [str(row["id"]) for row in cursor.fetchall()]
        count = sum(len(items) for items in result.values())
        return {"metric_key": metric_key, **result, "impact_count": count}


def _normalized_definition(definition: dict[str, Any]) -> dict[str, Any]:
    aggregation = str(definition.get("aggregationType") or "sum").lower()
    numerator = str(definition.get("numeratorField") or "")
    denominator = str(definition.get("denominatorField") or "")
    return {**definition, "definition": str(definition.get("definition") or definition.get("description") or definition.get("metricName") or ""), "aggregationType": aggregation, "valueExpression": f"ratio({numerator},{denominator})" if aggregation == "ratio" else str(definition.get("valueExpression") or definition.get("metricCode") or definition.get("metricId") or ""), "numeratorField": numerator, "denominatorField": denominator, "multiplier": float(definition.get("multiplier", 1)), "grain": _labels(definition.get("grain")), "dimensions": _labels(definition.get("dimension"))}


def _version_row(row: dict[str, Any], metric_key: str) -> dict[str, Any]:
    definition = {"metricId": metric_key, "definition": str(row["definition"]), "aggregationType": str(row["aggregation_type"]), "valueExpression": str(row["value_expression"]), "numeratorField": str(row.get("numerator_expression") or ""), "denominatorField": str(row.get("denominator_expression") or ""), "multiplier": float(row["multiplier"]), "grain": _decode(row.get("default_grain"), []), "dimension": _decode(row.get("allowed_dimensions"), []), "semanticStatus": str(row["status"]), "semanticVersion": f"v{row['version_no']}"}
    return {"version_id": str(row["metric_version_id"]), "metric_key": metric_key, "version_no": int(row["version_no"]), "status": str(row["status"]), "definition": definition, "checksum": str(row["checksum"]), "parent_version_id": str(row["parent_version_id"]) if row.get("parent_version_id") else None, "submitted_by": str(row["submitted_by"]) if row.get("submitted_by") else None, "reviewed_by": str(row["reviewed_by"]) if row.get("reviewed_by") else None, "review_comment": str(row.get("review_comment") or ""), "created_at": str(row["created_at"])}


def _resolve_tenant(cursor: Any, tenant_id: str) -> str:
    cursor.execute("SELECT tenant_id FROM platform_tenants WHERE tenant_code=%s AND status='active'", (tenant_id,))
    row = cursor.fetchone()
    if not row:
        raise PermissionError("tenant_not_provisioned")
    return str(row["tenant_id"])


def _resolve_user(cursor: Any, user_id: str) -> str:
    cursor.execute("SELECT user_id FROM platform_user_profiles WHERE external_subject=%s AND status='active'", (user_id,))
    row = cursor.fetchone()
    if not row:
        raise PermissionError("user_not_provisioned")
    return str(row["user_id"])


def _resolve_metric(cursor: Any, tenant_id: str, metric_key: str) -> tuple[str, str]:
    tenant_key = _resolve_tenant(cursor, tenant_id)
    cursor.execute("SELECT metric_id FROM platform_metric_dictionary WHERE tenant_id=%s AND metric_key=%s AND status<>'disabled'", (tenant_key, metric_key))
    row = cursor.fetchone()
    if not row:
        raise KeyError("metric_not_found")
    return tenant_key, str(row["metric_id"])


def _labels(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    return [item.strip() for item in str(value or "").replace("，", ",").split(",") if item.strip()]


def _decode(value: Any, default: Any) -> Any:
    if isinstance(value, type(default)):
        return value
    return json.loads(value) if value else deepcopy(default)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _required(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name}_required")
    return text


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
