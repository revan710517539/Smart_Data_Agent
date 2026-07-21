from __future__ import annotations

from typing import Callable

from backend.platform.semantic import SemanticQueryRequest, SemanticQueryService
from backend.platform.skills.models import SkillRequest, SkillResult, SkillSpec


def build_supersonic_query_skill(service: SemanticQueryService) -> tuple[SkillSpec, Callable[[SkillRequest], SkillResult]]:
    spec = SkillSpec(
        skill_id="supersonic.query",
        name="SuperSonic Semantic Query",
        skill_type="data_query",
        description="Route natural language questions through semantic models and SQL execution.",
        input_schema={
            "question": "string",
            "dataset_id": "string?",
            "metrics": "array?",
            "dimensions": "array?",
            "filters": "object?",
            "context": "object?",
            "limit": "integer?",
            "sort_direction": "string?",
        },
        output_schema={
            "sql": "string",
            "parameters": "object",
            "data": "array",
            "chart_spec": "object",
            "semantic_info": "object",
        },
        permission_scope=("data:query", "semantic:query"),
        risk_level="medium",
        runtime_type="supersonic",
    )

    def handler(request: SkillRequest) -> SkillResult:
        result = service.query(
            SemanticQueryRequest(
                question=str(request.inputs["question"]),
                tenant_id=request.context.tenant_id,
                user_id=request.context.user_id,
                dataset_id=request.inputs.get("dataset_id"),
                metrics=tuple(request.inputs.get("metrics", ())),
                dimensions=tuple(request.inputs.get("dimensions", ())),
                filters=dict(request.inputs.get("filters", {})),
                context=dict(request.inputs.get("context", {})),
                limit=int(request.inputs.get("limit") or 20),
                sort_direction=str(request.inputs.get("sort_direction") or "desc"),
            )
        )
        return SkillResult(
            skill_id=spec.skill_id,
            output={
                "sql": result.sql,
                "parameters": result.parameters,
                "data": result.data,
                "chart_spec": result.chart_spec,
                "semantic_info": result.semantic_info,
            },
            audit={"tenant_id": request.context.tenant_id, "row_count": len(result.data)},
        )

    return spec, handler
