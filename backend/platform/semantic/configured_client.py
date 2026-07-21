from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.platform.data_access.http_source import HTTPJSONSourceClient

from .models import SemanticQueryRequest, SemanticQueryResult
from .supersonic_client import SupersonicClient


class ConfiguredConnectionSupersonicClient:
    """Route tenant queries through a verified saved data connection first."""

    def __init__(self, system_config_store: Any, fallback: SupersonicClient) -> None:
        self.system_config_store = system_config_store
        self.fallback = fallback

    def close(self) -> None:
        close = getattr(self.fallback, "close", None)
        if callable(close):
            close()

    def query(self, request: SemanticQueryRequest) -> SemanticQueryResult:
        connection = self._select_connection(request)
        if connection is None:
            if request.context.get("manual_sql_candidate"):
                raise RuntimeError("manual_sql_requires_one_verified_tenant_connection")
            result = self.fallback.query(request)
            data_source = str(result.semantic_info.get("data_source") or "")
            existing_mode = str(result.semantic_info.get("execution_mode") or "").strip().lower()
            is_mock = existing_mode == "mock" or (not existing_mode and "mock" in data_source.lower())
            result.semantic_info.update(
                {
                    "connection_selection": "no_verified_tenant_connection",
                    "execution_mode": "mock" if is_mock else "real",
                    "publishable": not is_mock,
                }
            )
            return result
        return self._query_connection(connection, request)

    def _select_connection(self, request: SemanticQueryRequest) -> dict[str, Any] | None:
        connections = self.system_config_store.list_data_connections(request.tenant_id, reveal_secret=True)
        requested_connection_id = str(request.context.get("connection_id") or "").strip()
        eligible = [
            connection
            for connection in connections
            if connection.get("enabled")
            and not connection.get("mockEnabled")
            and str(connection.get("status") or "") == "verified"
            and str(connection.get("testStatus") or "") == "verified"
            and str(connection.get("dataset") or "") == str(request.dataset_id or "")
        ]
        if requested_connection_id:
            selected = next((item for item in eligible if str(item.get("id") or "") == requested_connection_id), None)
            if selected is None:
                raise PermissionError("Requested data connection is unavailable or not verified for this tenant and dataset.")
            return selected
        return eligible[0] if len(eligible) == 1 else None

    @staticmethod
    def _query_connection(connection: dict[str, Any], request: SemanticQueryRequest) -> SemanticQueryResult:
        query_payload = {
            "request_id": hashlib.sha256(
                f"{request.tenant_id}:{request.user_id}:{request.question}".encode("utf-8")
            ).hexdigest()[:24],
            "dataset_id": request.dataset_id,
            "tenant_id": request.tenant_id,
            "user_id": request.user_id,
            "metrics": list(request.metrics),
            "dimensions": list(request.dimensions),
            "filters": dict(request.filters),
            "context": dict(request.context),
            "limit": max(1, min(int(request.limit or 20), 500)),
            "sort_direction": "asc" if request.sort_direction.lower() == "asc" else "desc",
        }
        manual_sql = str(request.context.get("manual_sql_candidate") or "").strip()
        model_sql = str(request.context.get("model_sql_candidate") or "").strip()
        governed_sql = manual_sql or model_sql
        if governed_sql:
            # The existing provider contract accepts a governed SQL candidate under this
            # field; provenance is carried separately so providers need no breaking change.
            query_payload["manual_sql_candidate"] = governed_sql
            query_payload["sql_candidate_source"] = "manual" if manual_sql else "selected_model"
            query_payload["query_revision"] = int(request.context.get("query_revision") or 1)
        response = HTTPJSONSourceClient(connection).query(query_payload)
        result = response.get("result") if isinstance(response.get("result"), dict) else response
        rows = result.get("rows", result.get("data", []))
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise RuntimeError("configured_data_source_rows_invalid")
        semantic_info = result.get("semantic_info", result.get("semanticInfo", {}))
        if not isinstance(semantic_info, dict):
            raise RuntimeError("configured_data_source_semantic_info_invalid")
        required_filters = {
            key: value
            for key, value in request.filters.items()
            if value not in (None, "", "__context_tenant__")
        }
        required_filters.update(dict(request.context.get("authorization", {}).get("row_filter", {})))
        applied_filters = semantic_info.get("applied_filters")
        if not isinstance(applied_filters, dict) or any(applied_filters.get(key) != value for key, value in required_filters.items()):
            raise PermissionError("Configured data source did not confirm required row filters.")
        sql = str(result.get("sql") or "").strip()
        sql_executed = bool(sql)
        if governed_sql and (
            not sql_executed
            or semantic_info.get("catalog_validated") is not True
            or semantic_info.get("tenant_policy_injected") is not True
        ):
            raise PermissionError("SQL candidate was not catalog-validated and tenant-scoped by the data source.")
        provider_query_id = str(result.get("query_id") or query_payload["request_id"])
        if not sql:
            sql = (
                "-- Executed through configured HTTP data source; provider SQL is not exposed.\n"
                f"-- connection_id={connection.get('id')} query_id={provider_query_id}"
            )
        chart_spec = result.get("chart_spec", result.get("chartSpec", {}))
        if not isinstance(chart_spec, dict):
            chart_spec = {}
        dimension = request.dimensions[0] if request.dimensions else "dimension_value"
        chart_spec = {
            "type": str(chart_spec.get("type") or "bar"),
            "x": str(chart_spec.get("x") or dimension),
            "y": str(chart_spec.get("y") or "metric_value"),
            "title": str(chart_spec.get("title") or "可信数据源分析"),
        }
        parameters = result.get("parameters") if isinstance(result.get("parameters"), dict) else query_payload
        totals = semantic_info.get("totals")
        totals_complete = isinstance(totals, dict) and all(metric in totals for metric in request.metrics)
        snapshot = semantic_info.get("source_snapshot")
        snapshot_complete = isinstance(snapshot, dict) and bool(
            snapshot.get("snapshot_id") and snapshot.get("observed_at") and snapshot.get("immutable") is True
        )
        aggregation_semantics = semantic_info.get("metric_semantics")
        semantics_complete = isinstance(aggregation_semantics, dict) and all(
            isinstance(aggregation_semantics.get(metric), dict)
            and aggregation_semantics[metric].get("aggregation")
            and (
                not (metric.endswith("_rate") or metric == "roi")
                or (
                    aggregation_semantics[metric].get("aggregation") == "ratio"
                    and aggregation_semantics[metric].get("numerator")
                    and aggregation_semantics[metric].get("denominator")
                )
            )
            for metric in request.metrics
        )
        evidence_complete = totals_complete and snapshot_complete and semantics_complete
        semantic_info.update(
            {
                "dataset_id": request.dataset_id,
                "connection_id": str(connection.get("id") or ""),
                "data_source": f"configured_http:{connection.get('sourceType') or 'HTTP'}",
                "execution_mode": "real",
                "publishable": bool(semantic_info.get("publishable", True)) and evidence_complete,
                "evidence_complete": evidence_complete,
                "summary_complete": totals_complete,
                "aggregation_semantics_complete": semantics_complete,
                "provider_query_id": provider_query_id,
                "sql_executed": sql_executed,
                "manual_sql_applied": bool(manual_sql),
                "model_sql_applied": bool(model_sql and not manual_sql),
                "policy_enforced_at_source": True,
                "schema_mapping": {
                    "metric": request.metrics[0] if request.metrics else "metric_value",
                    "dimension": dimension,
                    "metrics": list(request.metrics),
                    "dimensions": list(request.dimensions),
                },
                "row_count": len(rows),
            }
        )
        return SemanticQueryResult(
            sql=sql,
            data=[dict(row) for row in rows],
            chart_spec=chart_spec,
            semantic_info=semantic_info,
            parameters=parameters,
        )
