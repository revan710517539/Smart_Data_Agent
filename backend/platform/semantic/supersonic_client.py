from __future__ import annotations

import json
import ssl
import time
from typing import Protocol
from urllib import error, request

import certifi
from backend.platform.data_access import DataWarehouse, JSONDataWarehouse
from backend.platform.security import EgressPolicyError, safe_urlopen

from .models import SemanticQueryRequest, SemanticQueryResult


class SupersonicClient(Protocol):
    """Boundary for the real SuperSonic service."""

    def query(self, request: SemanticQueryRequest) -> SemanticQueryResult:
        ...


class SupersonicClientError(RuntimeError):
    """Raised when the remote SuperSonic semantic service cannot return a valid result."""


class SupersonicHTTPClient:
    """HTTP adapter for a real SuperSonic semantic query service."""

    def __init__(
        self,
        endpoint: str,
        api_key: str | None = None,
        timeout_seconds: float = 8.0,
        retries: int = 1,
    ) -> None:
        if not endpoint:
            raise ValueError("Supersonic endpoint is required.")
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.retries = max(retries, 0)

    def query(self, semantic_request: SemanticQueryRequest) -> SemanticQueryResult:
        body = json.dumps(
            {
                "question": semantic_request.question,
                "tenant_id": semantic_request.tenant_id,
                "user_id": semantic_request.user_id,
                "dataset_id": semantic_request.dataset_id,
                "metrics": list(semantic_request.metrics),
                "dimensions": list(semantic_request.dimensions),
                "filters": semantic_request.filters,
                "context": semantic_request.context,
                "limit": max(1, min(int(semantic_request.limit or 20), 500)),
                "sort_direction": "asc" if semantic_request.sort_direction.lower() == "asc" else "desc",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                http_request = request.Request(self.endpoint, data=body, headers=headers, method="POST")
                with safe_urlopen(
                    http_request,
                    timeout=self.timeout_seconds,
                    context=ssl.create_default_context(cafile=certifi.where()),
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                result = self._parse_response(payload)
                result.semantic_info["supersonic_client"] = "http"
                result.semantic_info["fallback"] = False
                return result
            except error.HTTPError as exc:
                last_error = SupersonicClientError(f"supersonic_http_{exc.code}")
                if exc.code < 500 or attempt >= self.retries:
                    break
            except EgressPolicyError:
                raise
            except (TimeoutError, OSError, error.URLError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
            time.sleep(min(0.15 * (attempt + 1), 0.6))
        raise SupersonicClientError("supersonic_service_unavailable") from last_error

    @staticmethod
    def _parse_response(payload: dict) -> SemanticQueryResult:
        result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
        sql = result.get("sql")
        data = result.get("data", result.get("rows", []))
        chart_spec = result.get("chart_spec", result.get("chartSpec", {}))
        semantic_info = result.get("semantic_info", result.get("semanticInfo", {}))
        parameters = result.get("parameters", result.get("params", {}))
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError("Supersonic response missing sql.")
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise ValueError("Supersonic response data must be a list of objects.")
        if not isinstance(chart_spec, dict):
            raise ValueError("Supersonic response chart_spec must be an object.")
        if not isinstance(semantic_info, dict):
            raise ValueError("Supersonic response semantic_info must be an object.")
        if not isinstance(parameters, dict):
            raise ValueError("Supersonic response parameters must be an object.")
        return SemanticQueryResult(
            sql=sql,
            data=data,
            chart_spec=chart_spec,
            semantic_info=semantic_info,
            parameters=parameters,
        )


class FallbackSupersonicClient:
    """Try a primary client first, then preserve availability with a local semantic client."""

    def __init__(self, primary: SupersonicClient, fallback: SupersonicClient) -> None:
        self.primary = primary
        self.fallback = fallback

    def query(self, semantic_request: SemanticQueryRequest) -> SemanticQueryResult:
        try:
            return self.primary.query(semantic_request)
        except Exception:
            result = self.fallback.query(semantic_request)
            result.semantic_info["supersonic_client"] = "fallback"
            result.semantic_info["fallback"] = True
            result.semantic_info["fallback_reason"] = "primary_semantic_service_unavailable"
            return result

    def close(self) -> None:
        for client in (self.primary, self.fallback):
            close = getattr(client, "close", None)
            if callable(close):
                close()


class InMemorySupersonicClient:
    """Deterministic local stand-in for SuperSonic.

    It preserves the Supersonic stages so callers do not depend on direct SQL generation.
    """

    def __init__(self, warehouse: DataWarehouse | None = None) -> None:
        self.warehouse = warehouse or JSONDataWarehouse()

    def close(self) -> None:
        close = getattr(self.warehouse, "close", None)
        if callable(close):
            close()

    def query(self, request: SemanticQueryRequest) -> SemanticQueryResult:
        if str(request.context.get("manual_sql_candidate") or "").strip():
            # Raw SQL is not an executable client interface in the CSV-only
            # runtime.  Topic-table SQL remains an administrator-governed,
            # scheduled transformation; this blocks a manual candidate from
            # being silently ignored or routed to a retired data connection.
            raise RuntimeError("manual_sql_not_supported_in_csv_mode")
        metrics = tuple(
            self._safe_identifier(metric, self.warehouse.metric_universe(), "metric")
            for metric in (request.metrics or ("loan_amount",))
        )
        dimensions = tuple(
            self._safe_identifier(dimension, self.warehouse.dimension_universe(), "dimension")
            for dimension in (request.dimensions or ("branch_name",))
        )
        metric = metrics[0]
        dimension = dimensions[0]
        dataset_id = request.dataset_id or "loan_operation_mart"
        if not self.warehouse.has_dataset(dataset_id):
            raise ValueError(f"Unsupported dataset: {dataset_id}")
        filters = self._normalized_filters(request.filters)
        matrix_query = getattr(self.warehouse, "query_matrix", None)
        if not callable(matrix_query):
            raise RuntimeError("Configured warehouse does not support governed multi-metric execution.")
        warehouse_result = matrix_query(
            dataset_id=dataset_id,
            tenant_id=request.tenant_id,
            metrics=metrics,
            dimensions=dimensions,
            filters=filters,
            limit=max(1, min(int(request.limit or 20), 500)),
            sort_direction=request.sort_direction,
        )
        aggregate_expressions = ", ".join(
            f"{('avg' if aggregation == 'avg' else aggregation)}({metric_name}) as {metric_name}"
            for metric_name, aggregation in warehouse_result.aggregations.items()
        )
        data_source = getattr(self.warehouse, "data_source_name", "local_data_warehouse")
        sql = warehouse_result.sql or (
            f"-- NOT EXECUTED AS SQL: governed {data_source} non-SQL aggregation plan.\n"
            f"-- dataset={dataset_id}; dimensions={','.join(dimensions)}; metrics={','.join(metrics)}; "
            f"sort={request.sort_direction}; limit={max(1, min(int(request.limit or 20), 500))}; "
            f"filters={json.dumps(filters, ensure_ascii=False, sort_keys=True)}"
        )
        parameters = warehouse_result.parameters or {
            "tenant_id": request.tenant_id,
            "filters": filters,
            "limit": max(1, min(int(request.limit or 20), 500)),
            "sort_direction": request.sort_direction,
        }
        metric_semantics = warehouse_result.metric_semantics or {
            metric_name: {"aggregation": aggregation}
            for metric_name, aggregation in warehouse_result.aggregations.items()
        }
        unsafe_rate_metrics = sorted(
            metric_name
            for metric_name in metrics
            if (metric_name.endswith("_rate") or metric_name == "roi")
            and not (
                isinstance(metric_semantics.get(metric_name), dict)
                and metric_semantics[metric_name].get("aggregation") == "ratio"
                and metric_semantics[metric_name].get("numerator")
                and metric_semantics[metric_name].get("denominator")
            )
        )
        snapshot_reader = getattr(self.warehouse, "snapshot_info", None)
        source_snapshot = snapshot_reader(dataset_id) if callable(snapshot_reader) else {}
        snapshot_complete = bool(
            isinstance(source_snapshot, dict)
            and source_snapshot.get("snapshot_id")
            and source_snapshot.get("observed_at")
            and source_snapshot.get("immutable") is True
        )
        execution_mode = "mock" if "mock" in str(data_source).lower() else "real"
        sql_executed = bool(warehouse_result.sql)
        return SemanticQueryResult(
            sql=sql,
            parameters=parameters,
            data=warehouse_result.rows,
            chart_spec={
                "type": "line" if dimension == "month" else "bar",
                "x": dimension,
                "y": "metric_value",
                "title": self._chart_title(dimension, metric),
            },
            semantic_info={
                "dataset_id": dataset_id,
                "schema_mapping": {
                    "metric": metric,
                    "dimension": dimension,
                    "metrics": list(metrics),
                    "dimensions": list(dimensions),
                },
                "semantic_parser": "rule_then_llm",
                "semantic_corrector": "rule_validation",
                "semantic_translator": "semantic_to_sql",
                "filter_keys": sorted(filters),
                "supersonic_client": "local",
                "data_source": data_source,
                "execution_mode": execution_mode,
                "publishable": execution_mode == "real" and snapshot_complete and not unsafe_rate_metrics,
                "source_snapshot": source_snapshot,
                "sql_executed": sql_executed,
                "aggregation": warehouse_result.aggregations.get(metric, "sum"),
                "aggregations": dict(warehouse_result.aggregations),
                "metric_semantics": metric_semantics,
                "unsafe_rate_metrics": unsafe_rate_metrics,
                "aggregation_semantics_complete": not unsafe_rate_metrics,
                "evidence_complete": snapshot_complete and not unsafe_rate_metrics,
                "totals": dict(warehouse_result.totals),
                "summary_complete": True,
                "full_group_count": warehouse_result.full_group_count,
                "returned_group_count": len(warehouse_result.rows),
                "detail_limited": warehouse_result.full_group_count > len(warehouse_result.rows),
                "row_count": len(warehouse_result.rows),
                "fallback": False,
                "policy_enforced_at_source": True,
                "applied_filters": {"tenant_id": request.tenant_id, **filters},
            },
        )

    @staticmethod
    def _safe_identifier(value: str, allowed: set[str], field_name: str) -> str:
        if value not in allowed:
            raise ValueError(f"Unsupported {field_name}: {value}")
        return value

    def _normalized_filters(self, filters: dict) -> dict:
        normalized: dict = {}
        dimensions = self.warehouse.dimension_universe()
        for key, value in filters.items():
            if key == "tenant_id":
                continue
            if key not in dimensions:
                raise ValueError(f"Unsupported or non-enforceable filter field: {key}")
            if isinstance(value, dict):
                supported = {"eq", "in", "gte", "gt", "lte", "lt"}
                if set(value) - supported:
                    raise ValueError(f"Unsupported filter operator for {key}")
                normalized_value: dict = {}
                for operation, operand in value.items():
                    if operation == "in":
                        if not isinstance(operand, (list, tuple, set)):
                            raise ValueError(f"IN filter for {key} must be an array")
                        normalized_value[operation] = list(operand)
                    elif isinstance(operand, (str, int, float, bool)):
                        normalized_value[operation] = operand
                    else:
                        raise ValueError(f"Invalid filter value for {key}")
                normalized[key] = normalized_value
            elif isinstance(value, (list, tuple, set)):
                normalized[key] = list(value)
            elif isinstance(value, (str, int, float, bool)) and value != "":
                normalized[key] = value
        return normalized

    @staticmethod
    def _filter_sql(filters: dict) -> str:
        if not filters:
            return ""
        parts: list[str] = []
        for key, value in sorted(filters.items()):
            if isinstance(value, dict):
                for operation, operator in (("eq", "="), ("gte", ">="), ("gt", ">"), ("lte", "<="), ("lt", "<")):
                    if operation in value:
                        parts.append(f" and {key} {operator} :{key}_{operation}")
                if "in" in value:
                    parts.append(f" and {key} in :{key}_in")
            elif isinstance(value, list):
                parts.append(f" and {key} in :{key}_in")
            else:
                parts.append(f" and {key} = :{key}")
        return "".join(parts)

    @staticmethod
    def _chart_title(dimension: str, metric: str) -> str:
        dimension_labels = {
            "branch_name": "机构",
            "product_line": "产品线",
            "month": "月份",
            "channel": "渠道",
            "customer_segment": "客群",
        }
        metric_labels = {
            "loan_amount": "放款金额",
            "drawdown_rate": "动支率",
            "m1_overdue_rate": "M1逾期率",
            "loan_balance": "贷款余额",
            "customer_acquisition_cost": "获客成本",
            "roi": "ROI",
            "conversion_rate": "转化率",
            "active_customer_count": "活跃客户数",
        }
        return f"{dimension_labels.get(dimension, dimension)}维度{metric_labels.get(metric, metric)}分析"
