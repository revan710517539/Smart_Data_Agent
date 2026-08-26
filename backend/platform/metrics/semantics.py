from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SUPPORTED_AGGREGATIONS = {"sum", "avg", "count", "max", "min", "ratio"}


class MetricSemanticError(ValueError):
    """Raised when a requested metric cannot be bound to a governed definition."""


class MetricDictionaryReader(Protocol):
    def list(self, tenant_id: str) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class GovernedMetricDefinition:
    metric_code: str
    metric_name: str
    dataset_id: str
    aggregation: str
    version: str
    numerator: str = ""
    denominator: str = ""
    multiplier: float = 1.0
    unit: str = ""
    grain: str = ""
    source: str = "system_catalog"
    metric_id: str = ""

    def to_plan_payload(self) -> dict[str, Any]:
        return {
            "metric_code": self.metric_code,
            "metric_name": self.metric_name,
            "dataset_id": self.dataset_id,
            "aggregation": self.aggregation,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "multiplier": self.multiplier,
            "unit": self.unit,
            "grain": self.grain,
            "version": self.version,
            "source": self.source,
            "metric_id": self.metric_id,
        }


class MetricSemanticCatalog:
    """Resolve executable metrics from a reviewed system catalog and tenant dictionary.

    Free-text ``valueLogic`` is intentionally never parsed into SQL. A tenant can
    bind a metric to analysis only by supplying all structured semantic fields
    and publishing the definition. A tenant definition for a system metric must
    match the reviewed system formula; otherwise execution fails closed.
    """

    def __init__(
        self,
        definitions: tuple[GovernedMetricDefinition, ...],
        dictionary_store: MetricDictionaryReader | None = None,
    ) -> None:
        self._definitions = {(item.dataset_id, item.metric_code): item for item in definitions}
        self.dictionary_store = dictionary_store

    @classmethod
    def from_config_path(
        cls,
        path: str | Path,
        dictionary_store: MetricDictionaryReader | None = None,
    ) -> "MetricSemanticCatalog":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        raw_definitions = payload.get("metrics") if isinstance(payload, dict) else None
        if not isinstance(raw_definitions, list):
            raise MetricSemanticError("metric_semantic_catalog_invalid")
        definitions = tuple(
            _definition_from_payload(item, source="system_catalog")
            for item in raw_definitions
            if isinstance(item, dict)
        )
        if not definitions:
            raise MetricSemanticError("metric_semantic_catalog_empty")
        keys = [(item.dataset_id, item.metric_code) for item in definitions]
        if len(keys) != len(set(keys)):
            raise MetricSemanticError("metric_semantic_catalog_duplicate")
        return cls(definitions, dictionary_store)

    def resolve(self, tenant_id: str, dataset_id: str, metric_codes: tuple[str, ...]) -> list[dict[str, Any]]:
        if not metric_codes:
            raise MetricSemanticError("metric_semantic_metric_required")
        tenant_definitions = self._tenant_definitions(tenant_id)
        resolved: list[dict[str, Any]] = []
        for metric_code in metric_codes:
            baseline = self._definitions.get((dataset_id, metric_code))
            tenant_definition = tenant_definitions.get((dataset_id, metric_code))
            if baseline is None and tenant_definition is None:
                raise MetricSemanticError(f"metric_semantic_definition_missing:{dataset_id}:{metric_code}")
            if baseline is not None and tenant_definition is not None:
                _assert_formula_matches(baseline, tenant_definition)
            definition = tenant_definition or baseline
            if definition is None:  # pragma: no cover - guarded above.
                raise MetricSemanticError("metric_semantic_definition_missing")
            resolved.append(definition.to_plan_payload())
        return resolved

    def list_definitions(self, dataset_id: str) -> list[dict[str, Any]]:
        """Return reviewed system definitions for question-to-metric binding."""

        return [
            definition.to_plan_payload()
            for (definition_dataset, _), definition in self._definitions.items()
            if definition_dataset == dataset_id
        ]

    def _tenant_definitions(self, tenant_id: str) -> dict[tuple[str, str], GovernedMetricDefinition]:
        if self.dictionary_store is None:
            return {}
        definitions: dict[tuple[str, str], GovernedMetricDefinition] = {}
        for metric in self.dictionary_store.list(tenant_id):
            if str(metric.get("semanticStatus") or "documentation") != "published":
                continue
            if not str(metric.get("metricCode") or "").strip():
                continue
            definition = _definition_from_payload(
                {
                    "metric_code": metric.get("metricCode"),
                    "metric_name": metric.get("metricName"),
                    "dataset_id": metric.get("datasetId"),
                    "aggregation": metric.get("aggregationType"),
                    "numerator": metric.get("numeratorField"),
                    "denominator": metric.get("denominatorField"),
                    "multiplier": metric.get("multiplier", 1),
                    "unit": metric.get("unit"),
                    "grain": metric.get("grain"),
                    "version": metric.get("semanticVersion"),
                    "metric_id": metric.get("metricId"),
                },
                source="tenant_metric_dictionary",
            )
            key = (definition.dataset_id, definition.metric_code)
            if key in definitions:
                raise MetricSemanticError(
                    f"metric_semantic_published_definition_duplicate:{definition.dataset_id}:{definition.metric_code}"
                )
            definitions[key] = definition
        return definitions


def validate_metric_dictionary_semantics(metric: dict[str, Any]) -> None:
    """Validate structured execution fields without interpreting descriptive text."""

    status = str(metric.get("semanticStatus") or "documentation").strip().lower()
    if status not in {"documentation", "draft", "published", "deprecated"}:
        raise MetricSemanticError("metric_semantic_status_invalid")
    structured = any(
        str(metric.get(field) or "").strip()
        for field in ("metricCode", "datasetId", "aggregationType", "numeratorField", "denominatorField")
    )
    # Documentation-only entries may carry a legacy metricCode for display and
    # import traceability without being executable definitions.  Execution
    # only consumes published entries, so keep these records editable without
    # forcing unrelated dataset/aggregation fields to be fabricated.
    if status == "documentation":
        return
    if status == "draft" and not structured:
        return
    if status == "deprecated" and not structured:
        return
    _definition_from_payload(
        {
            "metric_code": metric.get("metricCode"),
            "metric_name": metric.get("metricName"),
            "dataset_id": metric.get("datasetId"),
            "aggregation": metric.get("aggregationType"),
            "numerator": metric.get("numeratorField"),
            "denominator": metric.get("denominatorField"),
            "multiplier": metric.get("multiplier", 1),
            "unit": metric.get("unit"),
            "grain": metric.get("grain"),
            "version": metric.get("semanticVersion"),
            "metric_id": metric.get("metricId"),
        },
        source="tenant_metric_dictionary",
    )


def _definition_from_payload(payload: dict[str, Any], *, source: str) -> GovernedMetricDefinition:
    metric_code = str(payload.get("metric_code") or "").strip()
    dataset_id = str(payload.get("dataset_id") or "").strip()
    aggregation = str(payload.get("aggregation") or "").strip().lower()
    numerator = str(payload.get("numerator") or "").strip()
    denominator = str(payload.get("denominator") or "").strip()
    version = str(payload.get("version") or "").strip()
    for field_name, value in (("metric_code", metric_code), ("dataset_id", dataset_id)):
        if not _IDENTIFIER.fullmatch(value):
            raise MetricSemanticError(f"metric_semantic_{field_name}_invalid")
    if aggregation not in _SUPPORTED_AGGREGATIONS:
        raise MetricSemanticError("metric_semantic_aggregation_invalid")
    if not version or len(version) > 64:
        raise MetricSemanticError("metric_semantic_version_invalid")
    if aggregation == "ratio":
        if not _IDENTIFIER.fullmatch(numerator) or not _IDENTIFIER.fullmatch(denominator):
            raise MetricSemanticError("metric_semantic_ratio_fields_invalid")
    elif numerator or denominator:
        raise MetricSemanticError("metric_semantic_ratio_fields_unexpected")
    try:
        multiplier = float(payload.get("multiplier", 1))
    except (TypeError, ValueError) as exc:
        raise MetricSemanticError("metric_semantic_multiplier_invalid") from exc
    if not (0 < multiplier <= 1_000_000):
        raise MetricSemanticError("metric_semantic_multiplier_invalid")
    return GovernedMetricDefinition(
        metric_code=metric_code,
        metric_name=str(payload.get("metric_name") or metric_code).strip()[:160],
        dataset_id=dataset_id,
        aggregation=aggregation,
        numerator=numerator,
        denominator=denominator,
        multiplier=multiplier,
        unit=str(payload.get("unit") or "").strip()[:32],
        grain=str(payload.get("grain") or "").strip()[:160],
        version=version,
        source=source,
        metric_id=str(payload.get("metric_id") or "").strip(),
    )


def _assert_formula_matches(
    baseline: GovernedMetricDefinition,
    tenant_definition: GovernedMetricDefinition,
) -> None:
    baseline_formula = (
        baseline.aggregation,
        baseline.numerator,
        baseline.denominator,
        baseline.multiplier,
    )
    tenant_formula = (
        tenant_definition.aggregation,
        tenant_definition.numerator,
        tenant_definition.denominator,
        tenant_definition.multiplier,
    )
    if baseline_formula != tenant_formula:
        raise MetricSemanticError(
            f"metric_semantic_formula_conflict:{baseline.dataset_id}:{baseline.metric_code}"
        )
