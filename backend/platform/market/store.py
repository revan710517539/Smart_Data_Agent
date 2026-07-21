from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.platform.storage import connect_sqlite


class SQLiteMarketStore:
    def __init__(self, db_path: str | Path, initialize: bool = False) -> None:
        self.db_path = str(db_path)
        self._conn = connect_sqlite(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._owns_connection = True
        if initialize:
            self.init_schema()

    def close(self) -> None:
        if self._owns_connection:
            self._conn.close()

    def init_schema(self) -> None:
        migration = Path(__file__).resolve().parents[1] / "database" / "sql" / "0011_market_monitoring.sql"
        self._conn.executescript(migration.read_text(encoding="utf-8"))
        self._conn.commit()

    def create_source(self, tenant_id: str, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
        source_system_id = _required(payload.get("source_system_id"), "source_system_id", 160)
        source_system = self._conn.execute(
            "SELECT * FROM platform_source_systems WHERE tenant_id = ? AND source_system_id = ?",
            (tenant_id, source_system_id),
        ).fetchone()
        if not source_system or str(source_system["source_category"]) != "market":
            raise ValueError("licensed_market_source_system_required")
        license_metadata = _load(source_system["license_metadata"], {})
        license_type = str(payload.get("license_type") or license_metadata.get("license_type") or "").strip()
        if not license_type:
            raise ValueError("market_license_type_required")
        acquisition_method = str(payload.get("acquisition_method") or "licensed_feed").strip()
        if acquisition_method not in {"api", "database", "file", "licensed_feed", "manual_review"}:
            raise ValueError("invalid_market_acquisition_method")
        source_id = str(payload.get("market_source_id") or f"ms_{uuid4().hex}")
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_market_sources(
                    tenant_id, market_source_id, source_system_id, source_url,
                    publisher, acquisition_method, license_type, reliability_score,
                    status, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    tenant_id, source_id, source_system_id,
                    str(payload.get("source_url") or "") or None,
                    _required(payload.get("publisher"), "publisher", 300),
                    acquisition_method, license_type,
                    max(0, min(float(payload.get("reliability_score", 0.8)), 1)),
                    created_by, now, now,
                ),
            )
        return self.get_source(tenant_id, source_id)

    def get_source(self, tenant_id: str, source_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM platform_market_sources WHERE tenant_id = ? AND market_source_id = ?",
            (tenant_id, source_id),
        ).fetchone()
        if not row:
            raise KeyError("market_source_not_found")
        return dict(row)

    def create_entity(self, tenant_id: str, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
        entity_type = str(payload.get("entity_type") or "institution").strip()
        if entity_type not in {"institution", "product", "industry", "region", "index", "event_subject"}:
            raise ValueError("invalid_market_entity_type")
        entity_id = str(payload.get("market_entity_id") or f"me_{uuid4().hex}")
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_market_entities(
                    tenant_id, market_entity_id, entity_type, entity_code, entity_name,
                    aliases, attributes, status, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    tenant_id, entity_id, entity_type,
                    _required(payload.get("entity_code"), "entity_code", 160),
                    _required(payload.get("entity_name"), "entity_name", 300),
                    _json(_list(payload.get("aliases", []))),
                    _json(_object(payload.get("attributes", {}))),
                    created_by, now, now,
                ),
            )
        return self.get_entity(tenant_id, entity_id)

    def get_entity(self, tenant_id: str, entity_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM platform_market_entities WHERE tenant_id = ? AND market_entity_id = ?",
            (tenant_id, entity_id),
        ).fetchone()
        if not row:
            raise KeyError("market_entity_not_found")
        result = dict(row)
        result["aliases"] = _load(result["aliases"], [])
        result["attributes"] = _load(result["attributes"], {})
        return result

    def create_observation(self, tenant_id: str, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
        source_id = _required(payload.get("market_source_id"), "market_source_id", 160)
        entity_id = _required(payload.get("market_entity_id"), "market_entity_id", 160)
        source = self.get_source(tenant_id, source_id)
        self.get_entity(tenant_id, entity_id)
        if source["status"] != "active":
            raise ValueError("market_source_is_not_active")
        artifact_id = _required(payload.get("evidence_artifact_id"), "evidence_artifact_id", 160)
        artifact = self._conn.execute(
            "SELECT status, content_hash FROM platform_data_artifacts WHERE tenant_id = ? AND artifact_id = ?",
            (tenant_id, artifact_id),
        ).fetchone()
        if not artifact or str(artifact["status"]) != "active":
            raise ValueError("active_market_evidence_artifact_required")
        observed_at = _timestamp(payload.get("observed_at"))
        value_numeric = payload.get("value_numeric")
        value_text = str(payload.get("value_text") or "").strip() or None
        if value_numeric is None and value_text is None:
            raise ValueError("market_observation_value_required")
        source_record_id = _required(payload.get("source_record_id"), "source_record_id", 300)
        observation_id = str(payload.get("market_observation_id") or f"mo_{uuid4().hex}")
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_market_observations(
                    tenant_id, market_observation_id, market_source_id, market_entity_id,
                    metric_code, observed_at, value_numeric, value_text, unit, currency,
                    evidence_artifact_id, source_record_id, confidence, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, market_source_id, source_record_id, metric_code) DO NOTHING
                """,
                (
                    tenant_id, observation_id, source_id, entity_id,
                    _required(payload.get("metric_code"), "metric_code", 160), observed_at,
                    float(value_numeric) if value_numeric is not None else None, value_text,
                    str(payload.get("unit") or "") or None,
                    str(payload.get("currency") or "")[:3] or None,
                    artifact_id, source_record_id,
                    max(0, min(float(payload.get("confidence", source["reliability_score"])), 1)),
                    created_by, now,
                ),
            )
        row = self._conn.execute(
            """
            SELECT * FROM platform_market_observations
            WHERE tenant_id = ? AND market_source_id = ? AND source_record_id = ? AND metric_code = ?
            """,
            (tenant_id, source_id, source_record_id, str(payload.get("metric_code"))),
        ).fetchone()
        assert row is not None
        return dict(row)

    def create_rule(self, tenant_id: str, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
        condition = _object(payload.get("condition_expression", {}))
        if str(condition.get("operator") or "") not in {"gt", "gte", "lt", "lte", "eq", "change_pct_gt", "change_pct_lt"}:
            raise ValueError("invalid_market_rule_operator")
        if "threshold" not in condition:
            raise ValueError("market_rule_threshold_required")
        severity = str(payload.get("severity") or "warning").strip()
        if severity not in {"info", "warning", "error", "critical"}:
            raise ValueError("invalid_market_rule_severity")
        rule_id = str(payload.get("market_rule_id") or f"mrule_{uuid4().hex}")
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_market_monitoring_rules(
                    tenant_id, market_rule_id, rule_name, entity_selector, metric_code,
                    condition_expression, severity, cooldown_seconds, status,
                    owner_user_id, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
                """,
                (
                    tenant_id, rule_id, _required(payload.get("rule_name"), "rule_name", 300),
                    _json(_object(payload.get("entity_selector", {}))),
                    _required(payload.get("metric_code"), "metric_code", 160),
                    _json(condition), severity,
                    max(0, min(int(payload.get("cooldown_seconds", 3600)), 31_536_000)),
                    created_by, created_by, now, now,
                ),
            )
        return self.get_rule(tenant_id, rule_id)

    def get_rule(self, tenant_id: str, rule_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM platform_market_monitoring_rules WHERE tenant_id = ? AND market_rule_id = ?",
            (tenant_id, rule_id),
        ).fetchone()
        if not row:
            raise KeyError("market_rule_not_found")
        result = dict(row)
        result["entity_selector"] = _load(result["entity_selector"], {})
        result["condition_expression"] = _load(result["condition_expression"], {})
        return result

    def list_rules(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT market_rule_id FROM platform_market_monitoring_rules WHERE tenant_id = ? ORDER BY created_at DESC",
            (tenant_id,),
        ).fetchall()
        return [self.get_rule(tenant_id, str(row["market_rule_id"])) for row in rows]

    def latest_observations(self, tenant_id: str, metric_code: str, limit_per_entity: int = 2) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT o.*, e.entity_type, e.entity_name, e.attributes, s.publisher, s.license_type,
                   a.content_hash AS evidence_hash
            FROM platform_market_observations o
            JOIN platform_market_entities e
              ON e.tenant_id = o.tenant_id AND e.market_entity_id = o.market_entity_id
            JOIN platform_market_sources s
              ON s.tenant_id = o.tenant_id AND s.market_source_id = o.market_source_id
            JOIN platform_data_artifacts a
              ON a.tenant_id = o.tenant_id AND a.artifact_id = o.evidence_artifact_id
            WHERE o.tenant_id = ? AND o.metric_code = ?
            ORDER BY o.market_entity_id, o.observed_at DESC
            """,
            (tenant_id, metric_code),
        ).fetchall()
        counts: dict[str, int] = {}
        result: list[dict[str, Any]] = []
        for row in rows:
            entity_id = str(row["market_entity_id"])
            if counts.get(entity_id, 0) >= limit_per_entity:
                continue
            item = dict(row)
            item["attributes"] = _load(item["attributes"], {})
            result.append(item)
            counts[entity_id] = counts.get(entity_id, 0) + 1
        return result

    def list_observations(self, tenant_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT o.*, e.entity_type, e.entity_name, e.attributes, s.publisher,
                   s.license_type, s.source_url, a.content_hash AS evidence_hash
            FROM platform_market_observations o
            JOIN platform_market_entities e
              ON e.tenant_id = o.tenant_id AND e.market_entity_id = o.market_entity_id
            JOIN platform_market_sources s
              ON s.tenant_id = o.tenant_id AND s.market_source_id = o.market_source_id
            JOIN platform_data_artifacts a
              ON a.tenant_id = o.tenant_id AND a.artifact_id = o.evidence_artifact_id
            WHERE o.tenant_id = ?
            ORDER BY o.observed_at DESC, o.created_at DESC
            LIMIT ?
            """,
            (tenant_id, max(1, min(int(limit), 5000))),
        ).fetchall()
        observations: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["attributes"] = _load(item["attributes"], {})
            observations.append(item)
        return observations

    def create_event(
        self,
        tenant_id: str,
        rule: dict[str, Any],
        observation: dict[str, Any],
        evidence: dict[str, Any],
    ) -> dict[str, Any] | None:
        existing = self._conn.execute(
            "SELECT * FROM platform_market_monitoring_events WHERE tenant_id = ? AND market_rule_id = ? AND observation_id = ?",
            (tenant_id, rule["market_rule_id"], observation["market_observation_id"]),
        ).fetchone()
        if existing:
            return None
        latest = self._conn.execute(
            """
            SELECT detected_at FROM platform_market_monitoring_events
            WHERE tenant_id = ? AND market_rule_id = ? AND market_entity_id = ?
              AND status IN ('open','acknowledged')
            ORDER BY detected_at DESC LIMIT 1
            """,
            (tenant_id, rule["market_rule_id"], observation["market_entity_id"]),
        ).fetchone()
        now_dt = datetime.now(timezone.utc)
        if latest:
            last = datetime.fromisoformat(str(latest["detected_at"]).replace("Z", "+00:00"))
            if (now_dt - last).total_seconds() < int(rule["cooldown_seconds"]):
                return None
        event_id = f"mke_{uuid4().hex}"
        now = now_dt.isoformat()
        summary = (
            f"{observation['entity_name']} 的 {rule['metric_code']} 触发规则“{rule['rule_name']}”，"
            f"当前值 {observation.get('value_numeric') if observation.get('value_numeric') is not None else observation.get('value_text')}。"
        )
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_market_monitoring_events(
                    tenant_id, market_event_id, market_rule_id, market_entity_id,
                    observation_id, severity, status, event_summary, evidence,
                    detected_at, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, 'system_market_monitor', ?, ?)
                """,
                (
                    tenant_id, event_id, rule["market_rule_id"], observation["market_entity_id"],
                    observation["market_observation_id"], rule["severity"], summary,
                    _json(evidence), now, now, now,
                ),
            )
            self._conn.execute(
                """
                INSERT INTO platform_outbox_events(
                    tenant_id, outbox_event_id, aggregate_type, aggregate_id,
                    event_type, payload, status, available_at, created_at, updated_at
                ) VALUES (?, ?, 'market_event', ?, 'market.monitoring.triggered', ?, 'pending', ?, ?, ?)
                """,
                (tenant_id, f"oe_{uuid4().hex}", event_id, _json({"market_event_id": event_id, "severity": rule["severity"], "summary": summary}), now, now, now),
            )
        return self.get_event(tenant_id, event_id)

    def get_event(self, tenant_id: str, event_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM platform_market_monitoring_events WHERE tenant_id = ? AND market_event_id = ?",
            (tenant_id, event_id),
        ).fetchone()
        if not row:
            raise KeyError("market_event_not_found")
        result = dict(row)
        result["evidence"] = _load(result["evidence"], {})
        return result

    def list_events(self, tenant_id: str, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT market_event_id FROM platform_market_monitoring_events WHERE tenant_id = ? ORDER BY detected_at DESC LIMIT ?",
            (tenant_id, max(1, min(int(limit), 500))),
        ).fetchall()
        return [self.get_event(tenant_id, str(row["market_event_id"])) for row in rows]

    def update_event_status(self, tenant_id: str, event_id: str, status: str, actor_user_id: str) -> dict[str, Any]:
        if status not in {"acknowledged", "resolved", "suppressed"}:
            raise ValueError("invalid_market_event_status")
        now = _utcnow()
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE platform_market_monitoring_events
                SET status = ?, acknowledged_by = ?, resolved_at = CASE WHEN ? = 'resolved' THEN ? ELSE resolved_at END,
                    updated_at = ?
                WHERE tenant_id = ? AND market_event_id = ?
                """,
                (status, actor_user_id, status, now, now, tenant_id, event_id),
            )
            if cursor.rowcount != 1:
                raise KeyError("market_event_not_found")
        return self.get_event(tenant_id, event_id)

    def bundle(self, tenant_id: str) -> dict[str, Any]:
        sources = [dict(row) for row in self._conn.execute(
            "SELECT * FROM platform_market_sources WHERE tenant_id = ? ORDER BY created_at DESC", (tenant_id,)
        ).fetchall()]
        entities = [self.get_entity(tenant_id, str(row["market_entity_id"])) for row in self._conn.execute(
            "SELECT market_entity_id FROM platform_market_entities WHERE tenant_id = ? ORDER BY created_at DESC", (tenant_id,)
        ).fetchall()]
        return {
            "sources": sources,
            "entities": entities,
            "observations": self.list_observations(tenant_id),
            "rules": self.list_rules(tenant_id),
            "events": self.list_events(tenant_id),
        }


class InMemoryMarketStore(SQLiteMarketStore):
    def __init__(self, acquisition_store: Any) -> None:
        self.db_path = ":memory:shared-acquisition"
        self._conn = acquisition_store._conn
        self._owns_connection = False
        self.init_schema()


def _required(value: Any, field: str, maximum: int) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"invalid_{field}")
    return normalized


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("json_object_required")
    return json.loads(json.dumps(value, ensure_ascii=False))


def _list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("json_list_required")
    return json.loads(json.dumps(value, ensure_ascii=False))


def _timestamp(value: Any) -> str:
    text = _required(value, "observed_at", 100)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("observed_at_timezone_required")
    return parsed.astimezone(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: Any, default: Any) -> Any:
    try:
        return json.loads(str(value)) if value not in (None, "") else default
    except (TypeError, json.JSONDecodeError):
        return default


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
