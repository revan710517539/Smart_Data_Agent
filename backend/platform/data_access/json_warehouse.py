from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_MOCK_WAREHOUSE_PATH = Path(__file__).resolve().parents[3] / "data" / "mock" / "semantic_datasets.json"


@dataclass(frozen=True)
class QueryRowsResult:
    dataset_id: str
    metric: str
    dimension: str
    aggregation: str
    rows: list[dict[str, Any]]
    sql: str | None = None
    parameters: dict[str, Any] | None = None


@dataclass(frozen=True)
class QueryMatrixResult:
    dataset_id: str
    metrics: tuple[str, ...]
    dimensions: tuple[str, ...]
    aggregations: dict[str, str]
    rows: list[dict[str, Any]]
    totals: dict[str, float]
    full_group_count: int
    sql: str | None = None
    parameters: dict[str, Any] | None = None
    metric_semantics: dict[str, dict[str, Any]] | None = None


class JSONDataWarehouse:
    """Tenant-aware local data warehouse backed by JSON.

    The class is deliberately small: it gives local/dev deployments a real data
    access boundary without requiring a database or warehouse. Production
    adapters can implement the same query contract against PostgreSQL, Hive, or
    a vendor warehouse.
    """

    data_source_name = "json_mock_warehouse"

    def __init__(self, path: str | Path = DEFAULT_MOCK_WAREHOUSE_PATH) -> None:
        self.path = Path(path)
        self._payload = self._load_payload()
        self._datasets: dict[str, dict[str, Any]] = self._payload.get("datasets", {})

    def list_datasets(self) -> list[dict[str, Any]]:
        return [
            {
                "dataset_id": dataset_id,
                "label": dataset.get("label", dataset_id),
                "allowed_metrics": list(dataset.get("allowed_metrics", [])),
                "allowed_dimensions": list(dataset.get("allowed_dimensions", [])),
                "row_count": len(dataset.get("rows", [])),
                "source": str(dataset.get("resolved_csv_path") or self.path),
            }
            for dataset_id, dataset in sorted(self._datasets.items())
        ]

    def metric_universe(self) -> set[str]:
        metrics: set[str] = set()
        for dataset in self._datasets.values():
            metrics.update(str(metric) for metric in dataset.get("allowed_metrics", []))
        return metrics

    def dimension_universe(self) -> set[str]:
        dimensions: set[str] = set()
        for dataset in self._datasets.values():
            dimensions.update(str(dimension) for dimension in dataset.get("allowed_dimensions", []))
        return dimensions

    def has_dataset(self, dataset_id: str) -> bool:
        return dataset_id in self._datasets

    def snapshot_info(self, dataset_id: str) -> dict[str, Any]:
        dataset = self._dataset(dataset_id)
        months = sorted(
            str(row.get("month"))
            for row in dataset.get("rows", [])
            if isinstance(row, dict) and row.get("month")
        )
        csv_path = Path(str(dataset.get("resolved_csv_path") or ""))
        artifact_sha256 = hashlib.sha256(csv_path.read_bytes()).hexdigest() if csv_path.is_file() else ""
        return {
            "snapshot_id": f"json-mock-{self._payload.get('version') or 'unknown'}-{dataset_id}",
            "observed_at": str(self._payload.get("version") or ""),
            "latest_partition": months[-1] if months else "",
            "artifact_sha256": artifact_sha256,
            "immutable": True,
            "mock": True,
        }

    def query(
        self,
        dataset_id: str,
        tenant_id: str,
        metric: str,
        dimension: str,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> QueryRowsResult:
        matrix = self.query_matrix(
            dataset_id=dataset_id,
            tenant_id=tenant_id,
            metrics=(metric,),
            dimensions=(dimension,),
            filters=filters,
            limit=limit,
        )
        return QueryRowsResult(
            dataset_id=dataset_id,
            metric=metric,
            dimension=dimension,
            aggregation=matrix.aggregations[metric],
            rows=[
                {
                    dimension: row.get(dimension),
                    "metric_value": row.get(metric, 0),
                    "metric_id": metric,
                }
                for row in matrix.rows
            ],
            parameters=matrix.parameters,
        )

    def query_matrix(
        self,
        dataset_id: str,
        tenant_id: str,
        metrics: tuple[str, ...],
        dimensions: tuple[str, ...],
        filters: dict[str, Any] | None = None,
        limit: int = 20,
        sort_direction: str = "desc",
    ) -> QueryMatrixResult:
        dataset = self._dataset(dataset_id)
        allowed_metrics = set(dataset.get("allowed_metrics", []))
        allowed_dimensions = set(dataset.get("allowed_dimensions", []))
        if not metrics or any(metric not in allowed_metrics for metric in metrics):
            raise ValueError(f"Unsupported metrics for {dataset_id}: {list(metrics)}")
        if not dimensions or any(dimension not in allowed_dimensions for dimension in dimensions):
            raise ValueError(f"Unsupported dimensions for {dataset_id}: {list(dimensions)}")
        metric_semantics = {
            metric: self._normalize_metric_semantics(
                dataset.get("metric_aggregation", {}).get(metric, "sum")
            )
            for metric in metrics
        }
        aggregations = {
            metric: str(metric_semantics[metric]["aggregation"])
            for metric in metrics
        }
        source_rows = [
            self._materialize_template_row(row, tenant_id)
            for row in dataset.get("rows", [])
            if self._row_matches_tenant(row, tenant_id)
        ]
        applied_filters = filters or {}
        filtered_rows = [row for row in source_rows if self._row_matches_filters(row, applied_filters)]
        grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for row in filtered_rows:
            key = tuple(row.get(dimension) for dimension in dimensions)
            if any(value in (None, "") for value in key):
                continue
            grouped.setdefault(key, []).append(row)
        output: list[dict[str, Any]] = []
        for key, group_rows in grouped.items():
            item = {dimension: key[index] for index, dimension in enumerate(dimensions)}
            for metric in metrics:
                item[metric] = self._aggregate_value(group_rows, metric, metric_semantics[metric])
            item["metric_value"] = item[metrics[0]]
            output.append(item)
        reverse = str(sort_direction).lower() != "asc"
        output.sort(key=lambda item: float(item.get(metrics[0]) or 0), reverse=reverse)
        bounded_limit = max(1, min(int(limit or 20), 500))
        totals = {
            metric: self._aggregate_value(filtered_rows, metric, metric_semantics[metric])
            for metric in metrics
        }
        return QueryMatrixResult(
            dataset_id=dataset_id,
            metrics=metrics,
            dimensions=dimensions,
            aggregations=aggregations,
            rows=output[:bounded_limit],
            totals=totals,
            full_group_count=len(output),
            parameters={
                "tenant_id": tenant_id,
                "filters": dict(applied_filters),
                "limit": bounded_limit,
                "sort_direction": "desc" if reverse else "asc",
            },
            metric_semantics=metric_semantics,
        )

    def _load_payload(self) -> dict[str, Any]:
        if not self.path.exists():
            raise FileNotFoundError(f"Mock warehouse JSON does not exist: {self.path}")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("datasets"), dict):
            raise ValueError("Mock warehouse JSON must contain a datasets object.")
        for dataset_id, dataset in payload["datasets"].items():
            if not isinstance(dataset, dict) or not dataset.get("csv_path"):
                continue
            csv_path = (self.path.parent / str(dataset["csv_path"])).resolve()
            root = self.path.parent.resolve()
            if csv_path.parent != root or not csv_path.is_file():
                raise ValueError(f"Mock warehouse CSV is outside data/mock or missing: {dataset_id}")
            integer_fields = {str(field) for field in dataset.get("integer_fields", [])}
            number_fields = {str(field) for field in dataset.get("number_fields", [])}
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = []
                for source_row in csv.DictReader(handle):
                    row: dict[str, Any] = dict(source_row)
                    for field in integer_fields:
                        if row.get(field) not in (None, ""):
                            row[field] = int(str(row[field]))
                    for field in number_fields:
                        if row.get(field) not in (None, ""):
                            row[field] = float(str(row[field]))
                    rows.append(row)
            dataset["rows"] = rows
            dataset["resolved_csv_path"] = str(csv_path)
        return payload

    def _dataset(self, dataset_id: str) -> dict[str, Any]:
        dataset = self._datasets.get(dataset_id)
        if not isinstance(dataset, dict):
            raise ValueError(f"Unknown dataset: {dataset_id}")
        return dataset

    @staticmethod
    def _row_matches_tenant(row: dict[str, Any], tenant_id: str) -> bool:
        row_tenant = str(row.get("tenant_id") or "")
        return row_tenant in {tenant_id, "*"}

    @staticmethod
    def _materialize_template_row(row: dict[str, Any], tenant_id: str) -> dict[str, Any]:
        materialized = dict(row)
        if materialized.get("tenant_id") == "*":
            materialized["tenant_id"] = tenant_id
        return materialized

    @staticmethod
    def _row_matches_filters(row: dict[str, Any], filters: dict[str, Any]) -> bool:
        for key, expected in filters.items():
            if key == "tenant_id" or expected in (None, "", "__context_tenant__"):
                continue
            if isinstance(expected, dict):
                actual = row.get(key)
                if "in" in expected:
                    values = expected.get("in")
                    if not isinstance(values, (list, tuple, set)) or actual not in values:
                        return False
                if "eq" in expected and actual != expected["eq"]:
                    return False
                if "gte" in expected and (actual is None or actual < expected["gte"]):
                    return False
                if "gt" in expected and (actual is None or actual <= expected["gt"]):
                    return False
                if "lte" in expected and (actual is None or actual > expected["lte"]):
                    return False
                if "lt" in expected and (actual is None or actual >= expected["lt"]):
                    return False
            elif isinstance(expected, (list, tuple, set)):
                if row.get(key) not in expected:
                    return False
            elif row.get(key) != expected:
                return False
        return True

    @staticmethod
    def _aggregate(rows: list[dict[str, Any]], metric: str, dimension: str, aggregation: str) -> list[dict[str, Any]]:
        grouped: dict[Any, list[float]] = {}
        for row in rows:
            key = row.get(dimension)
            if key in (None, ""):
                continue
            try:
                value = float(row.get(metric) or 0)
            except (TypeError, ValueError):
                value = 0.0
            grouped.setdefault(key, []).append(value)

        output: list[dict[str, Any]] = []
        for key, values in grouped.items():
            if aggregation == "avg":
                metric_value = sum(values) / len(values) if values else 0
            else:
                metric_value = sum(values)
            output.append(
                {
                    dimension: key,
                    "metric_value": round(metric_value, 6),
                    "metric_id": metric,
                }
            )
        return sorted(output, key=lambda item: float(item.get("metric_value") or 0), reverse=True)

    @staticmethod
    def _aggregate_value(
        rows: list[dict[str, Any]],
        metric: str,
        semantics: str | dict[str, Any],
    ) -> float:
        spec = JSONDataWarehouse._normalize_metric_semantics(semantics)
        aggregation = str(spec["aggregation"])
        if aggregation == "ratio":
            numerator = str(spec["numerator"])
            denominator = str(spec["denominator"])
            numerator_total = JSONDataWarehouse._sum_numeric(rows, numerator)
            denominator_total = JSONDataWarehouse._sum_numeric(rows, denominator)
            if denominator_total == 0:
                return 0.0
            return round(numerator_total * float(spec["multiplier"]) / denominator_total, 6)
        values: list[float] = []
        source_field = str(spec.get("field") or metric)
        for row in rows:
            try:
                values.append(float(row.get(source_field) or 0))
            except (TypeError, ValueError):
                continue
        if not values:
            return 0.0
        if aggregation == "avg":
            value = sum(values) / len(values)
        elif aggregation == "count":
            value = float(len(values))
        elif aggregation == "max":
            value = max(values)
        elif aggregation == "min":
            value = min(values)
        else:
            value = sum(values)
        return round(value, 6)

    @staticmethod
    def _sum_numeric(rows: list[dict[str, Any]], field: str) -> float:
        total = 0.0
        for row in rows:
            try:
                total += float(row.get(field) or 0)
            except (TypeError, ValueError):
                continue
        return total

    @staticmethod
    def _normalize_metric_semantics(value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            aggregation = value.strip().lower() or "sum"
            payload: dict[str, Any] = {"aggregation": aggregation}
        elif isinstance(value, dict):
            aggregation = str(value.get("aggregation") or "sum").strip().lower()
            payload = {
                "aggregation": aggregation,
                "field": str(value.get("field") or "").strip(),
                "numerator": str(value.get("numerator") or "").strip(),
                "denominator": str(value.get("denominator") or "").strip(),
                "multiplier": float(value.get("multiplier", 1)),
            }
        else:
            raise ValueError("Invalid metric aggregation definition")
        if aggregation not in {"sum", "avg", "count", "max", "min", "ratio"}:
            raise ValueError(f"Unsupported aggregation: {aggregation}")
        if aggregation == "ratio" and (not payload.get("numerator") or not payload.get("denominator")):
            raise ValueError("Ratio aggregation requires numerator and denominator")
        if aggregation != "ratio":
            payload.setdefault("numerator", "")
            payload.setdefault("denominator", "")
            payload.setdefault("multiplier", 1.0)
        return payload
