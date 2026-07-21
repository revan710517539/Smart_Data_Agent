from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .json_warehouse import QueryMatrixResult, QueryRowsResult


class DBAPIConnection(Protocol):
    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> Any:
        ...

    def close(self) -> None:
        ...


ConnectionFactory = Callable[[], DBAPIConnection]


@dataclass(frozen=True)
class MetricAggregationSpec:
    aggregation: str
    numerator: str = ""
    denominator: str = ""
    multiplier: float = 1.0


@dataclass(frozen=True)
class SQLDatasetSpec:
    dataset_id: str
    label: str
    source_table: str
    tenant_column: str
    allowed_metrics: tuple[str, ...]
    allowed_dimensions: tuple[str, ...]
    metric_aggregation: dict[str, MetricAggregationSpec]
    source_snapshot: dict[str, Any]


class SQLDataWarehouse:
    """DB-API based data warehouse adapter.

    It is intentionally conservative: dataset, metric, dimension, and table
    identifiers must come from a catalog before SQL is generated. Values remain
    parameterized so this adapter can back PostgreSQL, SQLite, or warehouse
    drivers with a thin connection factory.
    """

    data_source_name = "sqlite_dbapi_warehouse"

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        dataset_catalog: dict[str, dict[str, Any]],
        *,
        parameter_placeholder: str = "?",
    ) -> None:
        if parameter_placeholder not in {"?", "%s"}:
            raise ValueError("parameter_placeholder must be '?' or '%s'")
        self.connection_factory = connection_factory
        self.parameter_placeholder = parameter_placeholder
        self._datasets = {
            dataset_id: _normalize_dataset_spec(dataset_id, payload)
            for dataset_id, payload in dataset_catalog.items()
        }

    def list_datasets(self) -> list[dict[str, Any]]:
        return [
            {
                "dataset_id": spec.dataset_id,
                "label": spec.label,
                "source_table": spec.source_table,
                "allowed_metrics": list(spec.allowed_metrics),
                "allowed_dimensions": list(spec.allowed_dimensions),
                "source": "sql_warehouse",
                "source_snapshot": dict(spec.source_snapshot),
            }
            for spec in sorted(self._datasets.values(), key=lambda item: item.dataset_id)
        ]

    def metric_universe(self) -> set[str]:
        metrics: set[str] = set()
        for spec in self._datasets.values():
            metrics.update(spec.allowed_metrics)
        return metrics

    def dimension_universe(self) -> set[str]:
        dimensions: set[str] = set()
        for spec in self._datasets.values():
            dimensions.update(spec.allowed_dimensions)
        return dimensions

    def has_dataset(self, dataset_id: str) -> bool:
        return dataset_id in self._datasets

    def snapshot_info(self, dataset_id: str) -> dict[str, Any]:
        snapshot = dict(self._dataset(dataset_id).source_snapshot)
        if not snapshot.get("snapshot_id") or not snapshot.get("observed_at") or snapshot.get("immutable") is not True:
            return {}
        return snapshot

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
            sql=matrix.sql,
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
        spec = self._dataset(dataset_id)
        if not metrics or any(metric not in spec.allowed_metrics for metric in metrics):
            raise ValueError(f"Unsupported metrics for {dataset_id}: {list(metrics)}")
        if not dimensions or any(dimension not in spec.allowed_dimensions for dimension in dimensions):
            raise ValueError(f"Unsupported dimensions for {dataset_id}: {list(dimensions)}")
        metric_specs = {
            metric: spec.metric_aggregation.get(metric, MetricAggregationSpec("sum"))
            for metric in metrics
        }
        aggregations = {metric: definition.aggregation for metric, definition in metric_specs.items()}
        detail_sql, detail_parameters, total_sql, total_parameters, count_sql, count_parameters = self._build_matrix_sql(
            spec,
            tenant_id,
            metrics,
            dimensions,
            metric_specs,
            filters or {},
            limit,
            sort_direction,
        )
        connection = self.connection_factory()
        try:
            detail_cursor = connection.execute(detail_sql, detail_parameters)
            detail_rows = detail_cursor.fetchall()
            total_cursor = connection.execute(total_sql, total_parameters)
            total_row = total_cursor.fetchone()
            count_cursor = connection.execute(count_sql, count_parameters)
            count_row = count_cursor.fetchone()
        finally:
            close = getattr(connection, "close", None)
            if callable(close):
                close()

        rows: list[dict[str, Any]] = []
        for row in detail_rows:
            item = {dimension: row[index] for index, dimension in enumerate(dimensions)}
            metric_offset = len(dimensions)
            for index, metric_name in enumerate(metrics):
                item[metric_name] = round(float(row[metric_offset + index] or 0), 6)
            item["metric_value"] = item[metrics[0]]
            rows.append(item)
        totals = {
            metric_name: round(float(total_row[index] or 0), 6) if total_row is not None else 0.0
            for index, metric_name in enumerate(metrics)
        }
        return QueryMatrixResult(
            dataset_id=dataset_id,
            metrics=metrics,
            dimensions=dimensions,
            aggregations=aggregations,
            rows=rows,
            totals=totals,
            full_group_count=int(count_row[0] or 0) if count_row is not None else len(rows),
            sql=(
                f"-- detail query\n{detail_sql};\n"
                f"-- complete totals query\n{total_sql};\n"
                f"-- complete group count query\n{count_sql}"
            ),
            parameters={
                "values": list(detail_parameters),
                "detail_values": list(detail_parameters),
                "total_values": list(total_parameters),
                "tenant_id": tenant_id,
                "filters": dict(filters or {}),
                "limit": max(1, min(int(limit or 20), 500)),
                "sort_direction": "asc" if str(sort_direction).lower() == "asc" else "desc",
            },
            metric_semantics={
                metric: _metric_semantics_payload(definition)
                for metric, definition in metric_specs.items()
            },
        )

    def _dataset(self, dataset_id: str) -> SQLDatasetSpec:
        spec = self._datasets.get(dataset_id)
        if spec is None:
            raise ValueError(f"Unknown dataset: {dataset_id}")
        return spec

    def _build_sql(
        self,
        spec: SQLDatasetSpec,
        tenant_id: str,
        metric: str,
        dimension: str,
        aggregation: str,
        filters: dict[str, Any],
        limit: int,
    ) -> tuple[str, tuple[Any, ...]]:
        table = _quote_catalog_identifier(spec.source_table)
        tenant_column = _quote_identifier(spec.tenant_column)
        metric_column = _quote_identifier(metric)
        dimension_column = _quote_identifier(dimension)
        aggregate_expr = _aggregate_expression(MetricAggregationSpec(aggregation), metric_column)
        placeholder = self.parameter_placeholder
        where_clauses = [f"{tenant_column} = {placeholder}"]
        parameters: list[Any] = [tenant_id]

        allowed_filter_fields = set(spec.allowed_dimensions) | set(spec.allowed_metrics)
        for field_name, expected in sorted(filters.items()):
            if field_name == "tenant_id" or expected in (None, "", "__context_tenant__"):
                continue
            if field_name not in allowed_filter_fields:
                raise ValueError(f"Unsupported filter for {spec.dataset_id}: {field_name}")
            field_column = _quote_identifier(field_name)
            if isinstance(expected, (list, tuple, set)):
                values = list(expected)
                if not values:
                    continue
                placeholders = ", ".join(placeholder for _ in values)
                where_clauses.append(f"{field_column} IN ({placeholders})")
                parameters.extend(values)
            else:
                where_clauses.append(f"{field_column} = {placeholder}")
                parameters.append(expected)

        bounded_limit = max(1, min(int(limit or 20), 500))
        parameters.append(bounded_limit)
        sql = (
            f"SELECT {dimension_column} AS dimension_value, {aggregate_expr} AS metric_value "
            f"FROM {table} "
            f"WHERE {' AND '.join(where_clauses)} "
            f"GROUP BY {dimension_column} "
            f"ORDER BY metric_value DESC "
            f"LIMIT {placeholder}"
        )
        return sql, tuple(parameters)

    def _build_matrix_sql(
        self,
        spec: SQLDatasetSpec,
        tenant_id: str,
        metrics: tuple[str, ...],
        dimensions: tuple[str, ...],
        metric_specs: dict[str, MetricAggregationSpec],
        filters: dict[str, Any],
        limit: int,
        sort_direction: str,
    ) -> tuple[str, tuple[Any, ...], str, tuple[Any, ...], str, tuple[Any, ...]]:
        table = _quote_catalog_identifier(spec.source_table)
        dimension_columns = [_quote_identifier(dimension) for dimension in dimensions]
        metric_expressions = [
            f"{_aggregate_expression(metric_specs[metric], _quote_identifier(metric))} AS {_quote_identifier(metric)}"
            for metric in metrics
        ]
        where_clauses, parameters = self._build_where(spec, tenant_id, filters)
        select_dimensions = ", ".join(dimension_columns)
        select_metrics = ", ".join(metric_expressions)
        bounded_limit = max(1, min(int(limit or 20), 500))
        direction = "ASC" if str(sort_direction).lower() == "asc" else "DESC"
        detail_sql = (
            f"SELECT {select_dimensions}, {select_metrics} FROM {table} "
            f"WHERE {' AND '.join(where_clauses)} GROUP BY {select_dimensions} "
            f"ORDER BY {_quote_identifier(metrics[0])} {direction} LIMIT {self.parameter_placeholder}"
        )
        total_sql = f"SELECT {select_metrics} FROM {table} WHERE {' AND '.join(where_clauses)}"
        count_sql = (
            f"SELECT COUNT(*) FROM (SELECT 1 FROM {table} "
            f"WHERE {' AND '.join(where_clauses)} GROUP BY {select_dimensions}) AS grouped_rows"
        )
        return (
            detail_sql,
            tuple([*parameters, bounded_limit]),
            total_sql,
            tuple(parameters),
            count_sql,
            tuple(parameters),
        )

    def _build_where(
        self,
        spec: SQLDatasetSpec,
        tenant_id: str,
        filters: dict[str, Any],
    ) -> tuple[list[str], list[Any]]:
        placeholder = self.parameter_placeholder
        where_clauses = [f"{_quote_identifier(spec.tenant_column)} = {placeholder}"]
        parameters: list[Any] = [tenant_id]
        allowed_filter_fields = set(spec.allowed_dimensions) | set(spec.allowed_metrics)
        for field_name, expected in sorted(filters.items()):
            if field_name == "tenant_id" or expected in (None, "", "__context_tenant__"):
                continue
            if field_name not in allowed_filter_fields:
                raise ValueError(f"Unsupported filter for {spec.dataset_id}: {field_name}")
            field_column = _quote_identifier(field_name)
            if isinstance(expected, dict):
                supported = {"eq", "in", "gte", "gt", "lte", "lt"}
                if set(expected) - supported:
                    raise ValueError(f"Unsupported filter operator for {field_name}")
                if "eq" in expected:
                    where_clauses.append(f"{field_column} = {placeholder}")
                    parameters.append(expected["eq"])
                if "in" in expected:
                    values = expected["in"]
                    if not isinstance(values, (list, tuple, set)):
                        raise ValueError(f"IN filter for {field_name} must be an array")
                    values = list(values)
                    if not values:
                        where_clauses.append("1 = 0")
                    else:
                        where_clauses.append(f"{field_column} IN ({', '.join(placeholder for _ in values)})")
                        parameters.extend(values)
                for operation, operator in (("gte", ">="), ("gt", ">"), ("lte", "<="), ("lt", "<")):
                    if operation in expected:
                        where_clauses.append(f"{field_column} {operator} {placeholder}")
                        parameters.append(expected[operation])
            elif isinstance(expected, (list, tuple, set)):
                values = list(expected)
                if not values:
                    where_clauses.append("1 = 0")
                else:
                    where_clauses.append(f"{field_column} IN ({', '.join(placeholder for _ in values)})")
                    parameters.extend(values)
            else:
                where_clauses.append(f"{field_column} = {placeholder}")
                parameters.append(expected)
        return where_clauses, parameters


def _normalize_dataset_spec(dataset_id: str, payload: dict[str, Any]) -> SQLDatasetSpec:
    allowed_metrics = tuple(str(item) for item in payload.get("allowed_metrics", ()))
    allowed_dimensions = tuple(str(item) for item in payload.get("allowed_dimensions", ()))
    metric_aggregation = {
        str(metric): _normalize_metric_aggregation(str(metric), definition)
        for metric, definition in dict(payload.get("metric_aggregation", {})).items()
    }
    spec = SQLDatasetSpec(
        dataset_id=dataset_id,
        label=str(payload.get("label") or dataset_id),
        source_table=str(payload["source_table"]),
        tenant_column=str(payload.get("tenant_column") or "tenant_id"),
        allowed_metrics=allowed_metrics,
        allowed_dimensions=allowed_dimensions,
        metric_aggregation=metric_aggregation,
        source_snapshot=dict(payload.get("source_snapshot") or {}),
    )
    _quote_catalog_identifier(spec.source_table)
    _quote_identifier(spec.tenant_column)
    for identifier in (*spec.allowed_metrics, *spec.allowed_dimensions):
        _quote_identifier(identifier)
    return spec


def _normalize_metric_aggregation(metric: str, value: Any) -> MetricAggregationSpec:
    if isinstance(value, str):
        aggregation = value.strip().lower()
        definition = MetricAggregationSpec(aggregation=aggregation)
    elif isinstance(value, dict):
        aggregation = str(value.get("aggregation") or "").strip().lower()
        numerator = str(value.get("numerator") or "").strip()
        denominator = str(value.get("denominator") or "").strip()
        try:
            multiplier = float(value.get("multiplier", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid ratio multiplier for {metric}") from exc
        definition = MetricAggregationSpec(
            aggregation=aggregation,
            numerator=numerator,
            denominator=denominator,
            multiplier=multiplier,
        )
    else:
        raise ValueError(f"Invalid SQL aggregation definition for {metric}")
    if definition.aggregation not in {"sum", "avg", "count", "max", "min", "ratio"}:
        raise ValueError(f"Unsupported SQL aggregation: {definition.aggregation}")
    if definition.aggregation == "ratio":
        if not definition.numerator or not definition.denominator:
            raise ValueError(f"Ratio metric {metric} requires numerator and denominator")
        _quote_identifier(definition.numerator)
        _quote_identifier(definition.denominator)
        if not (definition.multiplier > 0):
            raise ValueError(f"Ratio metric {metric} multiplier must be positive")
    elif definition.numerator or definition.denominator:
        raise ValueError(f"Only ratio metrics may declare numerator or denominator: {metric}")
    return definition


def _aggregate_expression(definition: MetricAggregationSpec, metric_column: str) -> str:
    aggregation = definition.aggregation
    if aggregation == "ratio":
        numerator = _quote_identifier(definition.numerator)
        denominator = _quote_identifier(definition.denominator)
        return f"(SUM({numerator}) * {definition.multiplier:g}) / NULLIF(SUM({denominator}), 0)"
    if aggregation == "avg":
        return f"AVG({metric_column})"
    if aggregation == "count":
        return f"COUNT({metric_column})"
    if aggregation == "max":
        return f"MAX({metric_column})"
    if aggregation == "min":
        return f"MIN({metric_column})"
    return f"SUM({metric_column})"


def _metric_semantics_payload(definition: MetricAggregationSpec) -> dict[str, Any]:
    payload: dict[str, Any] = {"aggregation": definition.aggregation}
    if definition.aggregation == "ratio":
        payload.update(
            {
                "numerator": definition.numerator,
                "denominator": definition.denominator,
                "multiplier": definition.multiplier,
            }
        )
    return payload


def _quote_catalog_identifier(identifier: str) -> str:
    return ".".join(_quote_identifier(part) for part in identifier.split("."))


def _quote_identifier(identifier: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
        raise ValueError(f"Unsafe SQL identifier: {identifier}")
    return f'"{identifier}"'
