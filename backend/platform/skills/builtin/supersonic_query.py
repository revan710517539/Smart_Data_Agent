from __future__ import annotations

from typing import Any, Callable

from backend.platform.intelligent_analysis.uploaded_source import is_uploaded_analysis_table
from backend.platform.semantic import SemanticQueryRequest, SemanticQueryService
from backend.platform.skills.models import SkillRequest, SkillResult, SkillSpec


def build_supersonic_query_skill(
    service: SemanticQueryService,
    csv_source: Any | None = None,
) -> tuple[SkillSpec, Callable[[SkillRequest], SkillResult]]:
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
        selected_csv_result = _query_selected_csv(csv_source, request)
        if selected_csv_result is not None:
            return selected_csv_result
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


def _query_selected_csv(csv_source: Any | None, request: SkillRequest) -> SkillResult | None:
    context = request.inputs.get("context") if isinstance(request.inputs.get("context"), dict) else {}
    selected = context.get("selected_raw_table") if isinstance(context, dict) else None
    if not isinstance(selected, dict) or not selected:
        return None

    requested_id = str(selected.get("id") or "").strip()
    requested_path = str(selected.get("relativePath") or "").strip()
    if not requested_id or not requested_path:
        raise ValueError("selected_csv_reference_invalid")
    inline_selected = _is_inline_selected_table(selected)
    if inline_selected:
        authorized = selected
        source_rows = [dict(row) for row in selected.get("previewRows", []) if isinstance(row, dict)]
        headers = [str(field.get("fieldNameEn") or "") for field in selected.get("fields", []) if isinstance(field, dict)]
        if not source_rows or not headers:
            if str(selected.get("kind") or "") == "page_data":
                raise PermissionError("selected_multi_page_data_not_resolved")
            raise PermissionError("selected_uploaded_source_not_resolved")
    else:
        if csv_source is None:
            raise RuntimeError("selected_csv_source_unavailable")
        tenant_source = csv_source.for_tenant(request.context.tenant_id)
        catalog = tenant_source.table_assets(preview_limit=1)
        authorized = next(
            (
                table
                for table in catalog
                if str(table.get("id") or "").strip() == requested_id
                and str(table.get("relativePath") or "").strip() == requested_path
            ),
            None,
        )
        if authorized is None:
            requested_source_key = str(selected.get("sourceKey") or "").strip()
            if requested_source_key:
                authorized = next(
                    (
                        table
                        for table in catalog
                        if str(table.get("sourceKey") or "").strip() == requested_source_key
                    ),
                    None,
                )
        if authorized is None:
            raise PermissionError("selected_csv_not_published_or_not_authorized")
        # Daily deliveries keep superseded files on disk. Always read the
        # current catalog path, never the stale picker snapshot.
        headers, source_rows = tenant_source.read_rows(
            str(authorized.get("relativePath") or requested_path),
            max_rows=50_000,
        )
    fields = [field for field in authorized.get("fields") or [] if isinstance(field, dict)]
    page_data_selected = str(authorized.get("kind") or "") == "page_data"
    uploaded_selected = _is_uploaded_analysis_table(authorized)
    inline_lookup = page_data_selected or uploaded_selected
    code_to_header = {
        str(field.get("fieldNameEn") or "").strip(): (
            str(field.get("fieldNameEn") or "").strip()
            if inline_lookup
            else str(field.get("fieldNameCn") or field.get("fieldNameEn") or "").strip()
        )
        for field in fields
        if str(field.get("fieldNameEn") or "").strip()
    }
    allowed_codes = set(code_to_header)
    metrics = [str(item) for item in request.inputs.get("metrics") or []]
    dimensions = [str(item) for item in request.inputs.get("dimensions") or []]
    if any(metric != "row_count" and metric not in allowed_codes for metric in metrics):
        raise ValueError("selected_csv_metric_not_in_schema")
    if any(dimension not in allowed_codes for dimension in dimensions):
        raise ValueError("selected_csv_dimension_not_in_schema")
    if not metrics:
        raise ValueError("selected_csv_metric_required")

    plan = context.get("analysis_plan") if isinstance(context.get("analysis_plan"), dict) else {}
    definitions = {
        str(item.get("metric_code") or ""): item
        for item in plan.get("metric_definitions") or []
        if isinstance(item, dict) and str(item.get("metric_code") or "")
    }
    normalized_rows = [
        {
            code: row.get(header, "")
            for code, header in code_to_header.items()
            if header in headers
        }
        for row in source_rows
    ]
    grouped: dict[tuple[str, ...], dict[str, Any]] = {}
    metric_counts: dict[tuple[str, ...], dict[str, int]] = {}
    for row in normalized_rows:
        group_key = tuple(str(row.get(dimension) or "") for dimension in dimensions)
        output = grouped.setdefault(group_key, {dimension: row.get(dimension, "") for dimension in dimensions})
        counts = metric_counts.setdefault(group_key, {})
        for metric in metrics:
            definition = definitions.get(metric) or {}
            aggregation = str(definition.get("aggregation") or "sum").lower()
            if metric == "row_count":
                value = 1.0
            else:
                value = _csv_number(row.get(metric))
                if value is None:
                    continue
            if aggregation == "max":
                output[metric] = value if metric not in output else max(float(output[metric]), value)
            elif aggregation == "min":
                output[metric] = value if metric not in output else min(float(output[metric]), value)
            else:
                output[metric] = float(output.get(metric) or 0) + value
            counts[metric] = counts.get(metric, 0) + 1
    for group_key, output in grouped.items():
        for metric in metrics:
            definition = definitions.get(metric) or {}
            if str(definition.get("aggregation") or "").lower() == "avg" and metric in output:
                output[metric] = float(output[metric]) / max(1, metric_counts[group_key].get(metric, 0))

    rows = list(grouped.values())
    sort_metric = str(((plan.get("sort") or {}).get("metric")) or metrics[0])
    reverse = str(request.inputs.get("sort_direction") or "desc").lower() != "asc"
    rows.sort(key=lambda row: _csv_number(row.get(sort_metric)) or 0, reverse=reverse)
    full_group_count = len(rows)
    limit = max(1, min(int(request.inputs.get("limit") or 50), 500))
    rows = rows[:limit]
    totals = {
        metric: _aggregate_metric(normalized_rows, metric, definitions.get(metric) or {})
        for metric in metrics
    }
    dataset_id = str(request.inputs.get("dataset_id") or authorized.get("tableNameEn") or authorized.get("id") or requested_id)
    metric_semantics = {
        metric: {
            "aggregation": str((definitions.get(metric) or {}).get("aggregation") or "sum"),
            "numerator": str((definitions.get(metric) or {}).get("numerator") or ""),
            "denominator": str((definitions.get(metric) or {}).get("denominator") or ""),
            "multiplier": float((definitions.get(metric) or {}).get("multiplier") or 1),
            "source": "governed_page_data_schema" if page_data_selected else "temporary_table_schema",
        }
        for metric in metrics
    }
    field_labels = {
        code: str(
            code_to_header.get(code)
            or (definitions.get(code) or {}).get("metric_name")
            or code
        )
        for code in dict.fromkeys([*dimensions, *metrics])
    }
    if uploaded_selected:
        field_labels = {
            str(field.get("fieldNameEn") or ""): str(field.get("fieldNameCn") or field.get("fieldNameEn") or "")
            for field in fields
            if str(field.get("fieldNameEn") or "").strip()
        }
    sql = _csv_query_statement(dataset_id, metrics, dimensions, definitions)
    source_snapshot = {
        "table_id": str(authorized.get("id") or requested_id),
        "relative_path": str(authorized.get("relativePath") or requested_path),
        "content_hash": str(authorized.get("contentHash") or ""),
        "schema_fingerprint": str(authorized.get("schemaFingerprint") or ""),
        "source_key": str(authorized.get("sourceKey") or ""),
        "source_row_count": len(normalized_rows),
        **(
            {
                "page_data_id": requested_id,
                "relationship_group_id": str(authorized.get("relationshipGroupId") or ""),
                "institution_scope": "multi_institution",
            }
            if page_data_selected
            else {}
        ),
    }
    output = {
        "sql": sql,
        "parameters": {
            "tenant_id": request.context.tenant_id,
            "source_content_hash": source_snapshot["content_hash"],
        },
        "data": rows,
        "chart_spec": {
            "type": "line" if any("date" in str(code).lower() or "time" in str(code).lower() for code in dimensions) else "column",
            "x": dimensions[0] if dimensions else "",
            "y": metrics[0],
            "title": f"{authorized.get('tableNameCn') or dataset_id}分析",
        },
        "semantic_info": {
            "dataset_id": dataset_id,
            "data_source": (
                "governed_multi_institution_page_data" if page_data_selected
                else "uploaded_file" if uploaded_selected
                else "tenant_selected_raw_csv"
            ),
            "execution_mode": (
                "selected_multi_page_data" if page_data_selected
                else "uploaded_file" if uploaded_selected
                else "selected_raw_csv"
            ),
            "sql_executed": False,
            "policy_enforced_at_source": True,
            "publishable": bool(page_data_selected),
            "schema_mapping": {
                "metrics": metrics,
                "dimensions": dimensions,
                "field_labels": field_labels,
            },
            "metric_semantics": metric_semantics,
            "metric_definitions_bound": True,
            "metric_definition_versions": {
                metric: str((definitions.get(metric) or {}).get("version") or "temporary")
                for metric in metrics
            },
            "metric_definition_source": (
                "governed_page_data_schema" if page_data_selected
                else "uploaded_file_schema" if uploaded_selected
                else "temporary_table_schema"
            ),
            "aggregation_semantics_complete": True,
            "totals": totals,
            "full_group_count": full_group_count,
            "source_snapshot": source_snapshot,
            "page_data_identity": dict(authorized.get("sourceSnapshot") or {}) if page_data_selected else {},
        },
    }
    return SkillResult(
        skill_id="supersonic.query",
        output=output,
        audit={
            "tenant_id": request.context.tenant_id,
            "table_id": requested_id,
            "source_content_hash": source_snapshot["content_hash"],
            "source_row_count": len(normalized_rows),
            "returned_group_count": len(rows),
            "temporary_metric_semantics": True,
        },
    )


def _is_uploaded_analysis_table(table: dict[str, Any]) -> bool:
    return is_uploaded_analysis_table(table)


def _is_inline_selected_table(table: dict[str, Any]) -> bool:
    table_id = str(table.get("id") or "").strip()
    path = str(table.get("relativePath") or "").strip()
    kind = str(table.get("kind") or "").strip().lower()
    if is_uploaded_analysis_table(table):
        return True
    return bool(table_id) and path == f"page-data://{table_id}" and kind == "page_data"


def _csv_number(value: Any) -> float | None:
    text = str(value if value is not None else "").strip().replace(",", "")
    if not text or text in {"-", "--", "—", "N/A", "n/a"}:
        return None
    percentage = text.endswith("%")
    if percentage:
        text = text[:-1].strip()
    unit = 1.0
    if text.endswith("万"):
        text, unit = text[:-1].strip(), 10_000.0
    elif text.endswith("亿"):
        text, unit = text[:-1].strip(), 100_000_000.0
    try:
        number = float(text) * unit
    except ValueError:
        return None
    return number / 100 if percentage else number


def _aggregate_metric(rows: list[dict[str, Any]], metric: str, definition: dict[str, Any]) -> float:
    if metric == "row_count":
        return float(len(rows))
    values = [number for row in rows if (number := _csv_number(row.get(metric))) is not None]
    if not values:
        return 0.0
    aggregation = str(definition.get("aggregation") or "sum").lower()
    if aggregation == "avg":
        return sum(values) / len(values)
    if aggregation == "max":
        return max(values)
    if aggregation == "min":
        return min(values)
    if aggregation == "count":
        return float(len(values))
    return sum(values)


def _csv_query_statement(
    dataset_id: str,
    metrics: list[str],
    dimensions: list[str],
    definitions: dict[str, dict[str, Any]],
) -> str:
    dimension_sql = [f'"{field}"' for field in dimensions]
    metric_sql = []
    for metric in metrics:
        aggregation = str((definitions.get(metric) or {}).get("aggregation") or "sum").upper()
        expression = "COUNT(*)" if metric == "row_count" else f'{aggregation}("{metric}")'
        metric_sql.append(f'{expression} AS "{metric}"')
    select_sql = ", ".join([*dimension_sql, *metric_sql])
    group_sql = f"\nGROUP BY {', '.join(dimension_sql)}" if dimension_sql else ""
    return (
        "-- Selected tenant CSV; executed by the bounded read-only CSV adapter.\n"
        f'SELECT {select_sql}\nFROM "{dataset_id}"{group_sql}\nLIMIT 500;'
    )
