from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from backend.platform.observability import TraceRecorder

from .models import SemanticQueryRequest, SemanticQueryResult
from .supersonic_client import SupersonicClient

if TYPE_CHECKING:
    from backend.authz.models import MetricAccessDecision
    from backend.platform.governance import PermissionBroker


class SemanticQueryService:
    """Skill-facing SuperSonic query service."""

    def __init__(
        self,
        client: SupersonicClient,
        trace_recorder: TraceRecorder,
        permission_broker: "PermissionBroker | None" = None,
    ) -> None:
        self.client = client
        self.trace_recorder = trace_recorder
        self.permission_broker = permission_broker

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def query(self, request: SemanticQueryRequest) -> SemanticQueryResult:
        access_decision = self._metric_access_decision(request)
        self.trace_recorder.add_span(
            "supersonic.schema_mapping",
            inputs={"question": request.question, "tenant_id": request.tenant_id},
        )
        self.trace_recorder.add_span("supersonic.semantic_parse", inputs={"question": request.question})
        authorized_request = self._authorized_request(request, access_decision)
        result = self.client.query(authorized_request)
        self._validate_governed_metric_semantics(authorized_request, result)
        if access_decision and not result.semantic_info.get("policy_enforced_at_source"):
            raise PermissionError("Permission enforcement evidence missing from data source response.")
        result = self._apply_metric_access(result, access_decision)
        self.trace_recorder.add_span(
            "supersonic.sql_execution",
            inputs={"sql": result.sql},
            outputs={
                "row_count": len(result.data),
                "metric_access": {
                    "allowed": access_decision.allowed if access_decision else True,
                    "allowed_metric_ids": sorted(access_decision.allowed_metric_ids) if access_decision else [],
                    "allowed_fields": sorted(access_decision.allowed_fields) if access_decision else [],
                    "row_filter": access_decision.row_filter if access_decision else {},
                },
            },
        )
        return result

    @staticmethod
    def _validate_governed_metric_semantics(
        request: SemanticQueryRequest,
        result: SemanticQueryResult,
    ) -> None:
        definitions = request.context.get("analysis_plan", {}).get("metric_definitions", [])
        if not definitions:
            return
        if not isinstance(definitions, list) or any(not isinstance(item, dict) for item in definitions):
            raise ValueError("metric_semantic_plan_invalid")
        returned = result.semantic_info.get("metric_semantics")
        if not isinstance(returned, dict):
            raise ValueError("metric_semantic_evidence_missing")
        bound_versions: dict[str, str] = {}
        for definition in definitions:
            metric_code = str(definition.get("metric_code") or "")
            if metric_code not in request.metrics:
                raise ValueError("metric_semantic_plan_metric_mismatch")
            if str(definition.get("dataset_id") or "") != str(request.dataset_id or ""):
                raise ValueError("metric_semantic_plan_dataset_mismatch")
            actual = returned.get(metric_code)
            if not isinstance(actual, dict):
                raise ValueError(f"metric_semantic_evidence_missing:{metric_code}")
            expected_formula = (
                str(definition.get("aggregation") or "").lower(),
                str(definition.get("numerator") or ""),
                str(definition.get("denominator") or ""),
                float(definition.get("multiplier", 1)),
            )
            actual_formula = (
                str(actual.get("aggregation") or "").lower(),
                str(actual.get("numerator") or ""),
                str(actual.get("denominator") or ""),
                float(actual.get("multiplier", 1)),
            )
            if expected_formula != actual_formula:
                raise ValueError(f"metric_semantic_execution_mismatch:{metric_code}")
            bound_versions[metric_code] = str(definition.get("version") or "")
        result.semantic_info["metric_definition_versions"] = bound_versions
        result.semantic_info["metric_definitions_bound"] = True

    def _metric_access_decision(self, request: SemanticQueryRequest) -> "MetricAccessDecision | None":
        if self.permission_broker is None:
            return None
        metric_ids = set(request.metrics or ("loan_amount",))
        requested_fields = set(request.dimensions) | metric_ids | {"metric_value", "metric_id"}
        decision = self.permission_broker.enforcer.metric_access(
            user_id=request.user_id,
            tenant_id=request.tenant_id,
            metric_ids=metric_ids,
            requested_fields=requested_fields,
            metric_attrs={
                "dataset_id": request.dataset_id,
                **{key: value for key, value in request.filters.items() if key != "tenant_id"},
            },
        )
        self.trace_recorder.add_span(
            "authz.metric_filter",
            inputs={
                "tenant_id": request.tenant_id,
                "metric_ids": sorted(metric_ids),
                "requested_fields": sorted(requested_fields),
            },
            outputs={
                "allowed": decision.allowed,
                "allowed_metric_ids": sorted(decision.allowed_metric_ids),
                "allowed_fields": sorted(decision.allowed_fields),
                "row_filter": decision.row_filter,
            },
            status="ok" if decision.allowed else "denied",
        )
        if not decision.allowed:
            raise PermissionError("Permission denied: metric:*:read")
        if metric_ids and not decision.allowed_metric_ids:
            raise PermissionError("Permission denied: no requested metrics are allowed")
        if not metric_ids.issubset(decision.allowed_metric_ids):
            raise PermissionError("Permission denied: requested metric is outside the allowed scope")
        if not requested_fields.issubset(decision.allowed_fields):
            raise PermissionError("Permission denied: requested field is outside the allowed scope")
        return decision

    @staticmethod
    def _authorized_request(
        request: SemanticQueryRequest,
        decision: "MetricAccessDecision | None",
    ) -> SemanticQueryRequest:
        if decision is None:
            return request
        filters = dict(request.filters)
        for field_name, expected in decision.row_filter.items():
            existing = filters.get(field_name)
            if existing not in (None, "", "__context_tenant__", expected):
                raise PermissionError(f"Permission denied: filter conflicts with authorized scope for {field_name}")
            filters[field_name] = expected
        context = {
            **request.context,
            "authorization": {
                "allowed_metric_ids": sorted(decision.allowed_metric_ids),
                "allowed_fields": sorted(decision.allowed_fields),
                "row_filter": dict(decision.row_filter),
                "enforcement_required": "data_source",
            },
        }
        return replace(request, filters=filters, context=context)

    @staticmethod
    def _apply_metric_access(
        result: SemanticQueryResult,
        decision: "MetricAccessDecision | None",
    ) -> SemanticQueryResult:
        if decision is None:
            return result

        filtered_rows: list[dict] = []
        allowed_fields = set(decision.allowed_fields)

        for row in result.data:
            metric_id = row.get("metric_id")
            if metric_id and decision.allowed_metric_ids and metric_id not in decision.allowed_metric_ids:
                continue
            if allowed_fields:
                filtered_rows.append({key: value for key, value in row.items() if key in allowed_fields})
            else:
                filtered_rows.append(dict(row))

        semantic_info = dict(result.semantic_info)
        semantic_info["metric_access"] = {
            "filtered": len(filtered_rows) != len(result.data),
            "allowed_metric_ids": sorted(decision.allowed_metric_ids),
            "allowed_fields": sorted(decision.allowed_fields),
            "row_filter": decision.row_filter,
            "enforced_at_source": True,
        }
        return SemanticQueryResult(
            sql=result.sql,
            data=filtered_rows,
            chart_spec=result.chart_spec,
            semantic_info=semantic_info,
            parameters=result.parameters,
        )
