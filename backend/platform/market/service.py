from __future__ import annotations

from typing import Any


class MarketMonitoringService:
    def __init__(self, store: Any) -> None:
        self.store = store

    def create_source(self, tenant_id: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        return self.store.create_source(tenant_id, payload, actor)

    def create_entity(self, tenant_id: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        return self.store.create_entity(tenant_id, payload, actor)

    def create_observation(self, tenant_id: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        return self.store.create_observation(tenant_id, payload, actor)

    def create_rule(self, tenant_id: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        return self.store.create_rule(tenant_id, payload, actor)

    def evaluate(self, tenant_id: str, rule_id: str | None = None) -> dict[str, Any]:
        rules = [self.store.get_rule(tenant_id, rule_id)] if rule_id else self.store.list_rules(tenant_id)
        created: list[dict[str, Any]] = []
        evaluated = 0
        for rule in rules:
            if rule["status"] != "active":
                continue
            by_entity: dict[str, list[dict[str, Any]]] = {}
            for observation in self.store.latest_observations(tenant_id, rule["metric_code"], limit_per_entity=2):
                if not _selected(observation, rule["entity_selector"]):
                    continue
                by_entity.setdefault(str(observation["market_entity_id"]), []).append(observation)
            for observations in by_entity.values():
                latest = observations[0]
                previous = observations[1] if len(observations) > 1 else None
                evaluated += 1
                matched, calculated = _condition_matches(
                    latest.get("value_numeric"),
                    previous.get("value_numeric") if previous else None,
                    rule["condition_expression"],
                )
                if not matched:
                    continue
                evidence = {
                    "observation_id": latest["market_observation_id"],
                    "previous_observation_id": previous["market_observation_id"] if previous else None,
                    "evidence_artifact_id": latest["evidence_artifact_id"],
                    "evidence_hash": latest["evidence_hash"],
                    "publisher": latest["publisher"],
                    "license_type": latest["license_type"],
                    "observed_at": latest["observed_at"],
                    "confidence": latest["confidence"],
                    "calculated": calculated,
                    "condition": rule["condition_expression"],
                }
                event = self.store.create_event(tenant_id, rule, latest, evidence)
                if event:
                    created.append(event)
        return {"evaluated_observations": evaluated, "created_events": created, "created_count": len(created)}

    def bundle(self, tenant_id: str) -> dict[str, Any]:
        return self.store.bundle(tenant_id)


def _selected(observation: dict[str, Any], selector: dict[str, Any]) -> bool:
    entity_ids = selector.get("entity_ids")
    if isinstance(entity_ids, list) and entity_ids and observation["market_entity_id"] not in entity_ids:
        return False
    entity_types = selector.get("entity_types")
    if isinstance(entity_types, list) and entity_types and observation["entity_type"] not in entity_types:
        return False
    required_attributes = selector.get("attributes")
    if isinstance(required_attributes, dict):
        attributes = observation.get("attributes", {})
        if any(attributes.get(key) != value for key, value in required_attributes.items()):
            return False
    return True


def _condition_matches(current: Any, previous: Any, condition: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    if current is None:
        return False, {"reason": "numeric_value_required"}
    current_value = float(current)
    threshold = float(condition["threshold"])
    operator = str(condition["operator"])
    if operator.startswith("change_pct"):
        if previous in (None, 0):
            return False, {"reason": "previous_non_zero_value_required"}
        calculated_value = (current_value - float(previous)) / abs(float(previous)) * 100
        matched = calculated_value > threshold if operator == "change_pct_gt" else calculated_value < threshold
        return matched, {"value": calculated_value, "unit": "pct", "current": current_value, "previous": float(previous)}
    matched = {
        "gt": current_value > threshold,
        "gte": current_value >= threshold,
        "lt": current_value < threshold,
        "lte": current_value <= threshold,
        "eq": current_value == threshold,
    }.get(operator, False)
    return matched, {"value": current_value, "threshold": threshold}
