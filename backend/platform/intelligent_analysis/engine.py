from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from backend.platform.data_processing import PythonSandbox
from backend.platform.security.sql_validation import validate_read_only_sql_candidate
from backend.platform.settings import call_model_text_completion


PLANNING_PROMPT_TEMPLATE_ID = "intelligent_analysis.loan_analyst.plan.v3"
ANALYSIS_PROMPT_TEMPLATE_ID = "intelligent_analysis.loan_analyst.final.v3"


@dataclass(frozen=True)
class IntelligentAnalysisRequest:
    question: str
    tenant_id: str
    user_id: str
    analysis_plan: dict[str, Any] = field(default_factory=dict)
    asset_context: dict[str, Any] = field(default_factory=dict)
    skill: dict[str, Any] | None = None
    skills: list[dict[str, Any]] = field(default_factory=list)
    model: dict[str, Any] | None = None
    plugins: list[dict[str, Any]] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    conversation_context: dict[str, Any] = field(default_factory=dict)
    analysis_trigger: str = "manual"
    voice_silence_ms: int = 5000
    context_policy: dict[str, Any] = field(default_factory=dict)
    surface_context: dict[str, Any] = field(default_factory=dict)
    query_result: dict[str, Any] = field(default_factory=dict)


class IntelligentAnalysisEngine:
    """Two-stage selected-model pipeline with governed SQL/Python boundaries."""

    def run(self, request: IntelligentAnalysisRequest) -> dict[str, Any]:
        planning = self.plan(request)
        return self.analyze(request, planning)

    def plan(self, request: IntelligentAnalysisRequest) -> dict[str, Any]:
        skill_name = _skill_label(request)
        raw_sort = request.analysis_plan.get("sort")
        sort_direction = str(raw_sort.get("direction") or "desc") if isinstance(raw_sort, dict) else "desc"
        fallback = {
            "metrics": _safe_list(request.analysis_plan.get("metrics")),
            "dimensions": _safe_list(request.analysis_plan.get("dimensions")),
            "limit": max(1, min(int(request.analysis_plan.get("limit") or 50), 500)),
            "sort_direction": "asc" if sort_direction.lower() == "asc" else "desc",
            "sql": self._build_sql(request, skill_name),
            "data_processing_python": self._build_data_processing_python(request),
            "visualization_python": self._build_python(request, skill_name),
            "python_script": self._build_python(request, skill_name),
            "analysis_approach": self._build_approach(request, skill_name),
            "metric_scenarios": _build_metric_scenarios(request.analysis_plan),
            "visualization_suggestions": self._build_visualization_suggestions(request),
            "planning_source": "deterministic",
            "validation_errors": [],
        }
        if not isinstance(request.model, dict) or not request.model.get("id"):
            return {
                **fallback,
                "planning_invocation": {
                    "status": "skipped",
                    "callable": False,
                    "message": "未选择模型，使用受治理的确定性分析计划。",
                    "prompt_template_id": PLANNING_PROMPT_TEMPLATE_ID,
                },
            }
        prompt = _planning_prompt(request, skill_name, fallback)
        # The planning payload contains two sandboxed Python functions plus
        # metric scenarios.  A 2.6k cap can truncate otherwise valid JSON, so
        # use the provider boundary maximum and validate the complete object.
        completion = call_model_text_completion(request.model, prompt, max_tokens=3072)
        invocation = _safe_invocation(completion, PLANNING_PROMPT_TEMPLATE_ID)
        if completion.get("status") != "connected":
            return {**fallback, "planning_invocation": invocation}
        try:
            payload = _parse_model_json(str(completion.get("response_text") or ""))
            planning = _normalize_planning_payload(payload, fallback)
            return {**planning, "planning_invocation": invocation}
        except Exception as first_exc:
            retry_prompt = prompt + """

上一次响应未形成完整 JSON。请立即重试，并严格遵守：
- 总输出不超过 9000 个字符；不得输出空格缩进、Markdown、解释或注释。
- data_processing_python 与 visualization_python 各不超过 900 个字符。
- analysis_approach 最多 6 条，每条不超过 50 个汉字。
- 每个指标仅一个 metric_scenarios 项，每个情景不超过 60 个汉字。
- visualization_suggestions 最多 3 项。
- 必须闭合所有字符串、数组和对象。"""
            retry = call_model_text_completion(request.model, retry_prompt, max_tokens=3072)
            retry_invocation = _safe_invocation(retry, PLANNING_PROMPT_TEMPLATE_ID)
            retry_invocation["retry_count"] = 1
            retry_invocation["initial_error_code"] = "model_planning_output_invalid"
            if retry.get("status") == "connected":
                try:
                    payload = _parse_model_json(str(retry.get("response_text") or ""))
                    planning = _normalize_planning_payload(payload, fallback)
                    return {**planning, "planning_invocation": retry_invocation}
                except Exception as retry_exc:
                    first_exc = retry_exc
            invocation.update(
                {
                    "status": "failed",
                    "callable": False,
                    "error_code": "model_planning_output_invalid",
                    "message": str(first_exc)[:240],
                    "retry_count": 1,
                }
            )
            return {**fallback, "planning_invocation": invocation}

    def analyze(self, request: IntelligentAnalysisRequest, planning: dict[str, Any]) -> dict[str, Any]:
        skill_name = _skill_label(request)
        brief = _is_brief_follow_up(request)
        fallback_conclusions = self._build_brief_conclusions(request) if brief else self._build_conclusions(request, skill_name)
        fallback_summary = "\n".join(fallback_conclusions)
        visualization_suggestions = list(planning.get("visualization_suggestions") or self._build_visualization_suggestions(request))
        query_rows = request.query_result.get("data") if isinstance(request.query_result.get("data"), list) else []
        empty_query_result = not query_rows
        final_payload = {
            "analysis_summary": fallback_summary,
            "conclusions": fallback_conclusions,
            "metric_findings": [],
            "visualization_suggestions": [] if empty_query_result else visualization_suggestions,
            "conclusion_coverage": self._build_conclusion_coverage(request),
        }
        if empty_query_result:
            # A model cannot produce a factual conclusion without returned
            # rows. Finishing deterministically avoids the 30–60 second model
            # wait that previously followed an already completed empty query.
            model_invocation = {
                "status": "skipped",
                "callable": False,
                "message": "实际查询返回 0 行，跳过无数据情况下的模型结论调用。",
                "prompt_template_id": ANALYSIS_PROMPT_TEMPLATE_ID,
                "reason": "empty_query_result",
            }
        elif not isinstance(request.model, dict) or not request.model.get("id"):
            model_invocation = {
                "status": "skipped",
                "callable": False,
                "message": "未选择模型，保留基于执行证据的确定性结论。",
                "prompt_template_id": ANALYSIS_PROMPT_TEMPLATE_ID,
            }
        else:
            final_prompt = _final_analysis_prompt(request, skill_name, planning)
            completion = call_model_text_completion(
                request.model,
                final_prompt,
                max_tokens=3072,
            )
            model_invocation = _safe_invocation(completion, ANALYSIS_PROMPT_TEMPLATE_ID)
            if completion.get("status") == "connected":
                try:
                    payload = _parse_model_json(str(completion.get("response_text") or ""))
                    final_payload = _normalize_final_payload(payload, final_payload, request)
                except Exception as first_exc:
                    retry = call_model_text_completion(
                        request.model,
                        final_prompt + """

上一次响应不是完整可解析的 JSON。请仅返回一个闭合的 JSON 对象，并严格遵守：
- 不得输出 Markdown、代码围栏、解释或注释。
- analysis_summary 不超过 1200 个汉字；conclusions 最多 6 条，每条不超过 120 个汉字。
- metric_findings 最多 8 条；visualization_suggestions 最多 3 条。
- 必须闭合所有字符串、数组和对象。""",
                        max_tokens=3072,
                    )
                    retry_invocation = _safe_invocation(retry, ANALYSIS_PROMPT_TEMPLATE_ID)
                    retry_invocation["retry_count"] = 1
                    retry_invocation["initial_error_code"] = "model_final_output_invalid"
                    if retry.get("status") == "connected":
                        try:
                            payload = _parse_model_json(str(retry.get("response_text") or ""))
                            final_payload = _normalize_final_payload(payload, final_payload, request)
                            model_invocation = retry_invocation
                        except Exception as retry_exc:
                            model_invocation = retry_invocation
                            model_invocation.update(
                                {
                                    "status": "failed",
                                    "callable": False,
                                    "error_code": "model_final_output_invalid",
                                    "message": str(retry_exc)[:240],
                                }
                            )
                    else:
                        model_invocation = retry_invocation
        # Apply the same label and leakage guard to connected-model,
        # deterministic-fallback and no-model paths. Raw keys remain available
        # in query rows, SQL and evidence, but never become conclusion copy.
        final_payload = _normalize_final_payload(final_payload, final_payload, request)
        return {
            "planning": planning,
            "suggested_sql": str(planning.get("sql") or ""),
            "executed_sql": str(request.query_result.get("sql") or ""),
            "suggested_python_script": str(planning.get("python_script") or ""),
            "suggested_data_processing_python": str(planning.get("data_processing_python") or ""),
            "suggested_visualization_python": str(planning.get("visualization_python") or planning.get("python_script") or ""),
            "visualization_suggestions": final_payload["visualization_suggestions"],
            "analysis_approach": list(planning.get("analysis_approach") or []),
            "metric_scenarios": list(planning.get("metric_scenarios") or []),
            "metric_findings": final_payload["metric_findings"],
            "possible_conclusions": final_payload["conclusions"],
            "analysis_summary": final_payload["analysis_summary"],
            "conclusion_coverage": final_payload["conclusion_coverage"],
            "planning_invocation": dict(planning.get("planning_invocation") or {}),
            "model_invocation": model_invocation,
            "model_draft": final_payload["analysis_summary"],
            "runtime_chain": _runtime_chain(request, planning, model_invocation),
            "context": {
                "analysis_trigger": request.analysis_trigger,
                "skill": request.skill or None,
                "skills": request.skills,
                "model": _safe_model_context(request.model),
                "plugins": request.plugins,
                "files": request.files,
                "asset_context": request.asset_context,
                "conversation": request.conversation_context,
                "policy": request.context_policy,
            },
        }

    def _build_sql(self, request: IntelligentAnalysisRequest, skill_name: str) -> str:
        plan = request.analysis_plan
        dimensions = _safe_list(plan.get("dimensions")) or ["branch_name", "product_line"]
        metrics = _safe_list(plan.get("metrics")) or ["loan_amount", "m1_overdue_rate"]
        selected_tables = request.asset_context.get("selected_data_tables") if isinstance(request.asset_context, dict) else []
        selected_sql = ""
        selected_table_name = ""
        if isinstance(selected_tables, list) and selected_tables:
            first_table = next((table for table in selected_tables if isinstance(table, dict) and str(table.get("sql") or "").strip()), None)
            if isinstance(first_table, dict):
                selected_sql = str(first_table.get("sql") or "").strip()
                selected_table_name = str(first_table.get("name") or first_table.get("code") or "").strip()
        if selected_sql:
            return f"""-- IntelligentAnalysisEngine
-- Skill: {skill_name or "通用智能分析"}
-- Question: {request.question}
-- Selected data table: {selected_table_name or "用户选择的数据表"}
-- The selected table SQL is used first to fetch analysis data before LLM reasoning.
{_quote_known_tables(selected_sql)}"""
        topics = request.asset_context.get("topics") if isinstance(request.asset_context, dict) else []
        topic_sql = ""
        if isinstance(topics, list) and topics:
            topic_sql = str(topics[0].get("sql") or "").strip()
        if topic_sql:
            return f"""-- IntelligentAnalysisEngine
-- Skill: {skill_name or "通用智能分析"}
-- Question: {request.question}
-- Verified topic-table SQL reused below.
{_quote_known_tables(topic_sql)}"""
        dimension_select = ",\n  ".join(dimensions)
        metric_select = ",\n  ".join(_metric_expression(metric, index) for index, metric in enumerate(metrics))
        group_by = ", ".join(dimensions)
        return f"""-- IntelligentAnalysisEngine
-- Skill: {skill_name or "通用智能分析"}
-- Question: {request.question}
SELECT
  {dimension_select},
  {metric_select}
FROM "loan_operation_fact"
WHERE tenant_id = :tenant_id
  AND stat_date BETWEEN :start_date AND :end_date
GROUP BY {group_by}
ORDER BY metric_value DESC
LIMIT 50;"""

    def _build_python(self, request: IntelligentAnalysisRequest, skill_name: str) -> str:
        chart_type = _normalize_chart_type((_safe_list(request.analysis_plan.get("chart_types")) or ["column"])[0])
        return f'''def build_chart(data, context):
    x_field = context.get("x", "dimension_value")
    y_field = context.get("y", "metric_value")
    points = [
        {{"name": str(row.get(x_field, "")), "value": float(row.get(y_field, 0) or 0), "raw": row}}
        for row in data
    ]
    return {{
        "type": "{chart_type}",
        "title": context.get("title", "{skill_name or '通用智能分析'}"),
        "x": x_field,
        "y": y_field,
        "series": points,
        "table_rows": data,
    }}
'''

    def _build_data_processing_python(self, request: IntelligentAnalysisRequest) -> str:
        return '''def process_data(data, context):
    processed = [dict(row) for row in data]
    return {
        "rows": processed,
        "quality": {
            "input_row_count": len(data),
            "output_row_count": len(processed),
            "metric_definitions_bound": bool(context.get("metric_definitions_bound", False)),
            "metric_definition_versions": context.get("metric_definition_versions", {}),
            "totals": context.get("totals", {}),
        },
    }
'''

    def _build_visualization_suggestions(self, request: IntelligentAnalysisRequest) -> list[dict[str, Any]]:
        dimensions = _safe_list(request.analysis_plan.get("dimensions")) or ["branch_name", "product_line"]
        metrics = _safe_list(request.analysis_plan.get("metrics")) or ["metric_value"]
        labels = _field_labels_for_request(request)
        time_dimension = next((item for item in dimensions if _is_time_field_name(item)), "")
        detail_dimension = next((item for item in dimensions if item != time_dimension), dimensions[0])
        chart_types = ["line"] if time_dimension else []
        chart_types.extend(["column", "table"])
        suggestions: list[dict[str, Any]] = []
        for index, chart_type in enumerate(dict.fromkeys(chart_types)):
            dimension = time_dimension if chart_type == "line" and time_dimension else detail_dimension
            metric = metrics[min(index, len(metrics) - 1)]
            if chart_type == "line":
                purpose = "先看总体趋势、拐点和异常波动。"
            elif chart_type == "table":
                purpose = "最后保留必要明细，支持核对和继续下钻。"
            else:
                purpose = "再拆结构、排名和主要贡献分组。"
            suggestions.append(
                {
                    "type": chart_type,
                    "title": f"{_human_field_label(metric, labels)}按{_human_field_label(dimension, labels)}分析",
                    "dimension": dimension,
                    "metric": metric,
                    "purpose": purpose,
                }
            )
            if len(suggestions) >= 3:
                break
        return suggestions

    def _build_approach(self, request: IntelligentAnalysisRequest, skill_name: str) -> list[str]:
        file_note = f"结合 {len(request.files)} 个上传知识文件校验口径。" if request.files else "未上传知识文件，使用平台元数据和指标字典。"
        plugin_note = f"启用 {len(request.plugins)} 个插件补充上下文。" if request.plugins else "未选择额外插件。"
        selected_tables = request.asset_context.get("selected_data_tables") if isinstance(request.asset_context, dict) else []
        table_note = (
            f"优先使用用户选择的 {len(selected_tables)} 张数据表 SQL 获取数据。"
            if isinstance(selected_tables, list) and selected_tables
            else "未手动选择数据表，按语义匹配原始表和主题表。"
        )
        turn_count = int(request.conversation_context.get("turn_count") or 0) if isinstance(request.conversation_context, dict) else 0
        conversation_note = (
            f"延续当前登录会话的 {turn_count} 条上下文，并在需要时压缩为关键问题、SQL、结论和后续动作。"
            if turn_count
            else "当前为新分析会话，后续问题会继续沉淀到同一上下文。"
        )
        policy_note = (
            "与周报学习链路保持一致：多角色辩论用于经验沉淀，时间衰减用于行为偏好权重，不覆盖本轮事实数据。"
            if request.context_policy
            else "按当前问题、权限和元数据直接生成本轮分析结果。"
        )
        silence_seconds = max(1, request.voice_silence_ms) / 1000
        silence_label = str(int(silence_seconds)) if silence_seconds.is_integer() else f"{silence_seconds:g}"
        trigger_note = (
            f"本轮由实时语音 {silence_label} 秒静默自动触发，优先以输入框当前文本和用户已修改内容为准。"
            if request.analysis_trigger == "realtime_voice_silence"
            else "本轮由用户主动触发。"
        )
        scene_note = _scene_approach_note(request)
        return [
            trigger_note,
            scene_note,
            f"按“{skill_name or '通用智能分析'}”主题组织分析框架。",
            "先从指标字典、原始表、主题表中抽取可用指标和维度。",
            table_note,
            "生成 SQL 并获取数据，再用 Python 脚本渲染可视化报表。",
            file_note,
            plugin_note,
            conversation_note,
            policy_note,
            "最后结合业务口径输出结论、风险提示和后续动作。",
        ]

    def _build_brief_conclusions(self, request: IntelligentAnalysisRequest) -> list[str]:
        rows = [row for row in (request.query_result.get("data") or []) if isinstance(row, dict)]
        if not rows:
            return ["当前没有可分析的返回数据，请检查筛选或数据源。"]
        plan_metrics = _safe_list(request.analysis_plan.get("metrics"))
        plan_dims = _safe_list(request.analysis_plan.get("dimensions"))
        inferred_metrics, inferred_dims = _infer_fields_from_rows(rows)
        metrics = [item for item in plan_metrics if item in rows[0]] or inferred_metrics
        dimensions = [item for item in plan_dims if item in rows[0]] or inferred_dims
        time_dim = next((item for item in dimensions if _is_time_field_name(item)), "")
        category_dim = next((item for item in dimensions if item != time_dim), "")
        labels = _field_labels_for_request(request)
        highlights: list[str] = []
        for metric in metrics[:2]:
            metric_label = _human_field_label(metric, labels)
            if time_dim:
                highlights.extend(_brief_time_highlights(rows, metric, metric_label, time_dim, category_dim, labels))
            else:
                highlights.extend(_brief_rank_highlights(rows, metric, metric_label, category_dim or (dimensions[0] if dimensions else ""), labels))
        if not highlights:
            return [f"已返回 {len(rows)} 行数据，但没有可比较的数值字段。"]
        conclusion = "；".join(highlights[:2]) + "。"
        coverage = []
        if category_dim:
            groups = {str(row.get(category_dim) or "").strip() for row in rows if str(row.get(category_dim) or "").strip()}
            if groups:
                coverage.append(f"覆盖{_human_field_label(category_dim, labels)} {'、'.join(list(groups)[:4])}")
        if time_dim:
            points = sorted({str(row.get(time_dim) or "").strip() for row in rows if str(row.get(time_dim) or "").strip()})
            if points:
                time_label = _human_field_label(time_dim, labels)
                coverage.append(f"{time_label} {points[0]} 至 {points[-1]}" if len(points) > 1 else f"{time_label} {points[0]}")
        coverage.append(f"共 {len(rows)} 个数据点")
        description = "。".join(coverage) + "。"
        return [conclusion, description]

    def _build_conclusions(self, request: IntelligentAnalysisRequest, skill_name: str) -> list[str]:
        rows = request.query_result.get("data") if isinstance(request.query_result.get("data"), list) else []
        semantic_info = request.query_result.get("semantic_info") if isinstance(request.query_result.get("semantic_info"), dict) else {}
        mapping = semantic_info.get("schema_mapping") if isinstance(semantic_info.get("schema_mapping"), dict) else {}
        metrics = _safe_list(mapping.get("metrics")) or _safe_list(request.analysis_plan.get("metrics")) or ["核心经营指标"]
        dimensions = _safe_list(mapping.get("dimensions")) or _safe_list(request.analysis_plan.get("dimensions")) or ["分析维度"]
        metric = metrics[0]
        dimension = dimensions[0]
        data_source = str(semantic_info.get("data_source") or "unknown")
        execution_mode = str(semantic_info.get("execution_mode") or "")
        mode_label = "Mock 数据" if execution_mode == "mock" or "mock" in data_source.lower() else "已连接数据源数据"
        evidence = request.query_result.get("evidence") if isinstance(request.query_result.get("evidence"), dict) else {}
        evidence_id = str(evidence.get("evidence_id") or "未生成")
        totals = semantic_info.get("totals") if isinstance(semantic_info.get("totals"), dict) else {}
        definitions = {
            str(item.get("metric_code") or ""): item
            for item in (request.analysis_plan.get("metric_definitions") or [])
            if isinstance(item, dict) and str(item.get("metric_code") or "")
        }
        if not rows:
            return [
                f"本次已执行查询，但未返回可用于分析的 {metric} 数值；当前不能形成业务结论，请检查数据源、时间范围和权限。证据：{evidence_id}。"
            ]
        conclusions: list[str] = []
        for metric_name in metrics:
            numeric_rows = [
                (" / ".join(str(row.get(name) or "未命名维度") for name in dimensions), number)
                for row in rows
                if isinstance(row, dict) and (number := _safe_number(row.get(metric_name))) is not None
            ]
            if not numeric_rows:
                conclusions.append(f"{metric_name} 未返回可用数值，不能形成结论。证据：{evidence_id}。")
                continue
            top_value = max(value for _, value in numeric_rows)
            bottom_value = min(value for _, value in numeric_rows)
            top_names = [name for name, value in numeric_rows if value == top_value]
            bottom_names = [name for name, value in numeric_rows if value == bottom_value]
            zero_names = [name for name, value in numeric_rows if value == 0]
            definition = definitions.get(metric_name) or {}
            is_ratio = str(definition.get("aggregation") or "") == "ratio"
            anomaly_names = [
                name
                for name, value in numeric_rows
                if value < 0 or (is_ratio and value > 1)
            ]
            total = _safe_number(totals.get(metric_name))
            total_note = f"完整汇总为 {total:,.2f}" if total is not None else "完整汇总未返回"
            if top_value == bottom_value:
                extrema_note = f"全部 {len(numeric_rows)} 个分组均为 {top_value:,.2f}，不存在高低分化"
            else:
                extrema_note = (
                    f"最高为 {_summarize_group_names(top_names)} {top_value:,.2f}；"
                    f"最低为 {_summarize_group_names(bottom_names)} {bottom_value:,.2f}"
                )
            if is_ratio:
                numerator = str(definition.get("numerator") or "未绑定分子")
                denominator = str(definition.get("denominator") or "未绑定分母")
                definition_note = f"口径为 {numerator}/{denominator}"
            else:
                aggregation = str(definition.get("aggregation") or "sum")
                definition_note = f"口径为 {aggregation}({metric_name})"
            conclusions.append(
                f"基于 {mode_label}，{', '.join(dimensions)} 粒度下 {metric_name}：{extrema_note}；"
                f"零值分组 {len(zero_names)} 个；越界或负值异常分组 {len(anomaly_names)} 个；"
                f"{total_note}；{definition_note}。证据：{evidence_id}。"
            )
        conclusions.append("本次结果只陈述已执行证据中的指标、维度和值，不对未返回的原因、风险或业务指标作推断。")
        return conclusions

    def _build_conclusion_coverage(self, request: IntelligentAnalysisRequest) -> dict[str, Any]:
        metrics = _safe_list(request.analysis_plan.get("metrics"))
        dimensions = _safe_list(request.analysis_plan.get("dimensions"))
        rows = request.query_result.get("data") if isinstance(request.query_result.get("data"), list) else []
        semantic = request.query_result.get("semantic_info") if isinstance(request.query_result.get("semantic_info"), dict) else {}
        totals = semantic.get("totals") if isinstance(semantic.get("totals"), dict) else {}
        zero_value_groups = {
            metric: sum(
                1
                for row in rows
                if isinstance(row, dict) and _safe_number(row.get(metric)) == 0
            )
            for metric in metrics
        }
        extrema_covered_metrics = [
            metric
            for metric in metrics
            if any(isinstance(row, dict) and _safe_number(row.get(metric)) is not None for row in rows)
        ]
        anomaly_checked_metrics = list(extrema_covered_metrics)
        definition_codes = {
            str(item.get("metric_code") or "")
            for item in (request.analysis_plan.get("metric_definitions") or [])
            if isinstance(item, dict)
        }
        limitations = []
        full_group_count = int(semantic.get("full_group_count") or len(rows))
        if full_group_count > len(rows):
            limitations.append(f"页面仅展示 {len(rows)} / {full_group_count} 个分组，完整汇总值以 totals 为准。")
        if not rows:
            limitations.append("实际查询未返回分组数据，不能形成分组结论。")
        return {
            "metrics_covered": [metric for metric in metrics if metric in totals or any(isinstance(row, dict) and metric in row for row in rows)],
            "dimensions_covered": [dimension for dimension in dimensions if any(isinstance(row, dict) and dimension in row for row in rows)],
            "extrema_covered_metrics": extrema_covered_metrics,
            "anomaly_checked_metrics": anomaly_checked_metrics,
            "definition_bound_metrics": [metric for metric in metrics if metric in definition_codes],
            "zero_value_groups": zero_value_groups,
            "returned_group_count": len(rows),
            "full_group_count": full_group_count,
            "all_groups_returned": len(rows) == full_group_count,
            "limitations": limitations,
        }


def _planning_prompt(request: IntelligentAnalysisRequest, skill_name: str, fallback: dict[str, Any]) -> str:
    schema = {
        "metrics": ["仅从允许指标中选择"],
        "dimensions": ["仅从允许维度中选择"],
        "limit": 50,
        "sort_direction": "desc",
        "sql": "单条只读 SELECT/WITH，保留 :tenant_id、:start_date、:end_date 参数",
        "data_processing_python": "只定义 process_data(data, context) 的受限 Python，用于整理实际查询行并返回 rows 与 quality",
        "visualization_python": "只定义 build_chart(data, context) 的受限 Python",
        "analysis_approach": ["分析步骤"],
        "metric_scenarios": [
            {"metric": "指标", "positive": "表现较好时", "neutral": "表现平稳时", "negative": "表现较差时"}
        ],
        "visualization_suggestions": [
            {"type": "column", "title": "图表标题", "dimension": "维度", "metric": "指标", "purpose": "用途"}
        ],
        "conclusion_coverage": {
            "metrics_covered": ["实际覆盖指标"],
            "dimensions_covered": ["实际覆盖维度"],
            "zero_value_groups": {"指标": 0},
            "limitations": ["数据边界"]
        },
    }
    safe_plan = {
        "dataset_id": request.analysis_plan.get("dataset_id"),
        "metrics": fallback["metrics"],
        "dimensions": fallback["dimensions"],
        "filters": request.analysis_plan.get("filters") or {},
        "time_range": request.analysis_plan.get("time_range") or {},
        "chart_types": request.analysis_plan.get("chart_types") or [],
        "metric_definitions": request.analysis_plan.get("metric_definitions") or [],
    }
    return f"""你是金融贷款产品的数据分析规划模型。第一阶段只做场景/意图理解和可执行规划，不得编造实际数据结论。
问题：{request.question}
分析场景：{skill_name or '通用智能分析'}
场景判断：{json.dumps(_scene_prompt_context(request), ensure_ascii=False, sort_keys=True)}
分析方法要求：{_scene_kind_instructions(request)}
输入框完整上下文：{json.dumps(_model_input_context_for_prompt(request), ensure_ascii=False, sort_keys=True, default=str)}
服务端允许的分析计划：{json.dumps(safe_plan, ensure_ascii=False, sort_keys=True, default=str)}

请返回且只返回一个 JSON 对象，结构必须完全匹配：
{json.dumps(schema, ensure_ascii=False, sort_keys=True)}

约束：
1. metrics、dimensions 只能选择服务端允许清单中的值，不得创建新口径。
2. SQL 只能是一条只读 SELECT/WITH；禁止 DDL、DML、多语句和危险函数，并保留租户与时间参数。
3. 两段 Python 都禁止 import、文件、网络、反射和动态执行；数据加工只能定义 process_data(data, context)，可视化只能定义 build_chart(data, context)，并返回 JSON 可序列化对象。
4. metric_scenarios 必须穷举每个选中指标的较好、平稳、较差三类表现及分析方向，但不得声称这些情景已经发生。
5. analysis_approach 必须按“总体判断 → 趋势/结构拆解 → 异常或原因验证 → 经营动作”组织；先形成规划，再把匹配的 Skill 和 Memory 作为方法约束加入执行，不得用 Skill 名称代替分析步骤。
6. visualization_suggestions 必须从总到分：优先总体趋势，其次机构/产品/客群/渠道结构，最后必要明细；最多3项。
7. 没有合适 Skill 或 Memory 时，使用通用贷款分析框架：规模、转化/效率、收益、风险、客群与机构差异，并严格受现有字段约束。
8. 总 JSON 不超过 9000 个字符；两段 Python 各不超过 900 个字符且不要注释；分析步骤最多6条，情景文字每项不超过60个汉字。
9. 不要输出 Markdown、解释性前后缀或代码围栏。"""


def _final_analysis_prompt(request: IntelligentAnalysisRequest, skill_name: str, planning: dict[str, Any]) -> str:
    safe_planning = {
        key: planning.get(key)
        for key in (
            "metrics",
            "dimensions",
            "sql",
            "python_script",
            "data_processing_python",
            "visualization_python",
            "analysis_approach",
            "metric_scenarios",
            "visualization_suggestions",
        )
    }
    safe_planning["metric_definitions"] = request.analysis_plan.get("metric_definitions") or []
    schema = {
        "analysis_summary": "按核心结论、数据证据、原因边界、经营建议、风险提示、后续动作组织的中文总结",
        "conclusions": ["只引用执行证据的结论"],
        "metric_findings": [
            {"metric": "指标", "observed": "实际表现", "interpretation": "分析", "evidence": "证据ID或字段"}
        ],
        "visualization_suggestions": [
            {"type": "column", "title": "图表标题", "dimension": "维度", "metric": "指标", "purpose": "用途"}
        ],
    }
    output_mode = "右侧 AI 分析栏，摘要不超过360字、结论最多4条" if _is_brief_follow_up(request) else "完整分析页面，摘要不超过700字、结论最多6条"
    return f"""你是金融贷款产品的数据分析师。现在执行唯一运行时的第二阶段：融合第一阶段规划、已调度 Skill、相关 Memory 与实际取数证据，生成最终页面结果。
问题：{request.question}
分析场景：{skill_name or '通用智能分析'}
场景判断：{json.dumps(_scene_prompt_context(request), ensure_ascii=False, sort_keys=True)}
分析方法要求：{_scene_kind_instructions(request)}
输入框完整上下文：{json.dumps(_model_input_context_for_prompt(request), ensure_ascii=False, sort_keys=True, default=str)}
第一阶段规划：{json.dumps(safe_planning, ensure_ascii=False, sort_keys=True, default=str)}
实际执行证据：{_query_evidence_for_prompt(request.query_result)}
输出场景：{output_mode}

请返回且只返回一个 JSON 对象，结构必须完全匹配：
{json.dumps(schema, ensure_ascii=False, sort_keys=True)}

约束：
1. 只能依据实际执行证据陈述事实；没有返回的指标必须明确写“未返回”，不得套用情景结论冒充事实。
2. 先给总体判断，再给趋势/结构，随后解释已被数据验证的主要驱动或明确原因边界，最后给1至3项经营动作；不把相关性写成因果。
3. 每条结论必须包含业务中文名和关键数字；同一个事实只说一次，禁止同义反复、模板套话、SQL、证据ID、技术字段名、下划线字段名或数据库表名出现在用户可见文字中。
4. visualization_suggestions 只能使用 line、column、table，并从总到分组织：总体趋势 → 机构/产品/客群/渠道结构 → 必要明细；绑定实际返回的指标和维度。
5. 对返回指标覆盖总体值、头尾差异和明显异常；证据不足时明确“当前数据无法判断原因”，不得补写未经验证的风险或建议。
6. analysis_summary 使用短句和数字，{output_mode}；metric_findings 只保留不重复的关键发现。
7. 若输入上下文包含 conclusion_generation_rules，必须逐数据集按输入顺序处理规则列表，只用实际执行证据计算并判断每条 metricRules 的 operator、threshold 与 thresholdEnd；仅采用条件确实命中的 conclusion 表达规则，将多个数据集的命中规则去重融合，再遵循相应已调度 Skill 的 output_format 和表达方法。规则只能约束表达，不能替代或改写实际证据。
8. 不要输出 Markdown、解释性前后缀或代码围栏。"""


def _safe_invocation(completion: dict[str, Any], prompt_template_id: str) -> dict[str, Any]:
    result = {
        key: completion.get(key)
        for key in (
            "status",
            "error_code",
            "request_hash",
            "response_hash",
            "latency_ms",
            "input_tokens",
            "output_tokens",
            "usage_source",
            "model_id",
            "used_model",
            "message",
        )
        if completion.get(key) not in (None, "")
    }
    result["callable"] = completion.get("status") == "connected"
    result["prompt_template_id"] = prompt_template_id
    return result


def _parse_model_json(response_text: str) -> dict[str, Any]:
    text = response_text.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        payload = None
        if start >= 0:
            depth = 0
            in_string = False
            escaped = False
            for index, character in enumerate(text[start:], start=start):
                if in_string:
                    if escaped:
                        escaped = False
                    elif character == "\\":
                        escaped = True
                    elif character == '"':
                        in_string = False
                    continue
                if character == '"':
                    in_string = True
                elif character == "{":
                    depth += 1
                elif character == "}":
                    depth -= 1
                    if depth == 0:
                        payload = json.loads(text[start : index + 1])
                        break
        if payload is None:
            raise
    if not isinstance(payload, dict):
        raise ValueError("model_output_must_be_json_object")
    return payload


def _normalize_planning_payload(payload: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    allowed_metrics = set(fallback["metrics"])
    allowed_dimensions = set(fallback["dimensions"])
    metrics = [item for item in _safe_list(payload.get("metrics")) if item in allowed_metrics] or list(fallback["metrics"])
    dimensions = [item for item in _safe_list(payload.get("dimensions")) if item in allowed_dimensions] or list(fallback["dimensions"])

    sql = str(payload.get("sql") or "").strip()
    try:
        sql = validate_read_only_sql_candidate(sql) if sql else str(fallback["sql"])
    except Exception:
        sql = str(fallback["sql"])
        errors.append("model_sql_rejected")

    data_processing_python = str(payload.get("data_processing_python") or "").strip()
    try:
        PythonSandbox().validate_processing_code(data_processing_python)
    except Exception:
        data_processing_python = str(fallback["data_processing_python"])
        errors.append("model_data_processing_python_rejected")

    python_script = str(payload.get("visualization_python") or payload.get("python_script") or "").strip()
    try:
        PythonSandbox().validate_code(python_script)
    except Exception:
        python_script = str(fallback["python_script"])
        errors.append("model_python_rejected")

    approach = _safe_list(payload.get("analysis_approach"))[:12] or list(fallback["analysis_approach"])
    scenarios = _normalize_metric_scenarios(payload.get("metric_scenarios"), metrics) or list(fallback["metric_scenarios"])
    visualizations = _normalize_visualizations(payload.get("visualization_suggestions"), metrics, dimensions)
    if not visualizations:
        visualizations = list(fallback["visualization_suggestions"])
    try:
        limit = max(1, min(int(payload.get("limit") or fallback["limit"]), 500))
    except (TypeError, ValueError):
        limit = int(fallback["limit"])
    return {
        "metrics": metrics,
        "dimensions": dimensions,
        "limit": limit,
        "sort_direction": "asc" if str(payload.get("sort_direction") or "").lower() == "asc" else "desc",
        "sql": sql,
        "python_script": python_script,
        "data_processing_python": data_processing_python,
        "visualization_python": python_script,
        "analysis_approach": approach,
        "metric_scenarios": scenarios,
        "visualization_suggestions": visualizations,
        "planning_source": "model",
        "validation_errors": errors,
    }


def _normalize_final_payload(
    payload: dict[str, Any],
    fallback: dict[str, Any],
    request: IntelligentAnalysisRequest,
) -> dict[str, Any]:
    brief = _is_brief_follow_up(request)
    conclusion_limit = 4 if brief else 6
    summary_limit = 360 if brief else 700
    labels = _field_labels_for_request(request)
    raw_conclusions = _safe_list(payload.get("conclusions")) or list(fallback["conclusions"])
    conclusions = _dedupe_user_text(raw_conclusions, labels, limit=conclusion_limit, item_limit=160)
    if not conclusions:
        conclusions = _dedupe_user_text(fallback["conclusions"], labels, limit=conclusion_limit, item_limit=160)
    raw_summary = str(payload.get("analysis_summary") or "").strip() or "\n".join(conclusions)
    summary = _sanitize_user_text(raw_summary, labels, summary_limit)
    summary = _dedupe_summary_sentences(summary, summary_limit) or "\n".join(conclusions)
    findings = [
        {
            "metric": _human_field_label(str(item.get("metric") or "").strip(), labels),
            "observed": _sanitize_user_text(str(item.get("observed") or ""), labels, 120),
            "interpretation": _sanitize_user_text(str(item.get("interpretation") or ""), labels, 160),
            "evidence": "已执行数据证据",
        }
        for item in (payload.get("metric_findings") or [])
        if isinstance(item, dict) and str(item.get("metric") or "").strip()
    ][:6]
    visualizations = _normalize_visualizations(payload.get("visualization_suggestions"), [], [])
    for item in visualizations:
        item["title"] = _sanitize_user_text(str(item.get("title") or ""), labels, 80)
        item["purpose"] = _sanitize_user_text(str(item.get("purpose") or ""), labels, 100)
    return {
        "analysis_summary": summary,
        "conclusions": conclusions,
        "metric_findings": findings,
        "visualization_suggestions": visualizations or list(fallback["visualization_suggestions"]),
        # Coverage is computed from executed evidence, never trusted from the
        # language model.  This makes exhaustiveness auditable and deterministic.
        "conclusion_coverage": dict(fallback.get("conclusion_coverage") or {}),
    }


def _field_labels_for_request(request: IntelligentAnalysisRequest) -> dict[str, str]:
    rows = [row for row in (request.query_result.get("data") or []) if isinstance(row, dict)]
    labels = _field_labels_from_rows(rows)
    semantic = request.query_result.get("semantic_info") if isinstance(request.query_result.get("semantic_info"), dict) else {}
    mapping = semantic.get("schema_mapping") if isinstance(semantic.get("schema_mapping"), dict) else {}
    for source in (
        request.query_result.get("field_labels"),
        request.query_result.get("fieldLabels"),
        semantic.get("field_labels"),
        semantic.get("fieldLabels"),
        mapping.get("field_labels"),
        mapping.get("fieldLabels"),
    ):
        if isinstance(source, dict):
            labels.update({str(key): str(value).strip() for key, value in source.items() if str(value).strip()})
    selected_tables = request.asset_context.get("selected_data_tables") if isinstance(request.asset_context, dict) else []
    for table in selected_tables if isinstance(selected_tables, list) else []:
        table_mapping = table.get("schema_mapping") if isinstance(table, dict) and isinstance(table.get("schema_mapping"), dict) else {}
        for source in (
            table.get("fieldLabels") if isinstance(table, dict) else None,
            table.get("field_labels") if isinstance(table, dict) else None,
            table_mapping.get("field_labels"),
            table_mapping.get("fieldLabels"),
        ):
            if isinstance(source, dict):
                labels.update({str(key): str(value).strip() for key, value in source.items() if str(value).strip()})
        for field in table.get("fields") if isinstance(table, dict) and isinstance(table.get("fields"), list) else []:
            if not isinstance(field, dict):
                continue
            code = str(field.get("fieldNameEn") or field.get("code") or "").strip()
            name = str(field.get("fieldNameCn") or field.get("name") or "").strip()
            if code and name:
                labels[code] = name
    for definition in request.analysis_plan.get("metric_definitions") or []:
        if not isinstance(definition, dict):
            continue
        code = str(definition.get("metric_code") or definition.get("metricCode") or "").strip()
        name = str(definition.get("metric_name") or definition.get("metricName") or "").strip()
        if code and name:
            labels[code] = name
    for code in [*_safe_list(request.analysis_plan.get("metrics")), *_safe_list(request.analysis_plan.get("dimensions"))]:
        labels.setdefault(code, _human_field_label(code))
    return labels


def _sanitize_user_text(value: str, labels: dict[str, str], limit: int) -> str:
    text = str(value or "").strip()
    for code, label in sorted(labels.items(), key=lambda item: len(item[0]), reverse=True):
        if code and label and code != label:
            text = text.replace(code, label)
    text = re.sub(r"\bev_[a-fA-F0-9]{8,}\b", "", text)
    text = re.sub(r"\b(?:SELECT|FROM|WHERE|GROUP BY|ORDER BY|LIMIT)\b[^。；\n]*", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\b[a-zA-Z][a-zA-Z0-9]*(?:_[a-zA-Z0-9]+)+\b",
        lambda match: _human_field_label(match.group(0), labels),
        text,
    )
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"([，；。])\1+", r"\1", text)
    return text.strip(" \n，；")[:limit]


def _dedupe_user_text(
    values: list[Any],
    labels: dict[str, str],
    *,
    limit: int,
    item_limit: int,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _sanitize_user_text(str(value or ""), labels, item_limit)
        key = re.sub(r"[\s，。；：、,.!?！？]", "", text).casefold()
        if not text or not key or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _dedupe_summary_sentences(value: str, limit: int) -> str:
    parts = [part.strip() for part in re.split(r"(?<=[。！？；\n])", value) if part.strip()]
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        key = re.sub(r"[\s，。；：、,.!?！？]", "", part).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(part)
    return "\n".join(result)[:limit].strip()


def _build_metric_scenarios(plan: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "metric": metric,
            "positive": f"{metric} 优于目标或同业时，分析增长来源、可复制机构和资源投入效率。",
            "neutral": f"{metric} 基本稳定时，分析结构分化、边际变化和潜在拐点。",
            "negative": f"{metric} 低于目标或明显下降时，拆解机构、产品、客群、渠道和时间贡献。",
        }
        for metric in _safe_list(plan.get("metrics"))
    ]


def _normalize_metric_scenarios(value: Any, metrics: list[str]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    allowed = set(metrics)
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        metric = str(item.get("metric") or "").strip()
        if metric not in allowed:
            continue
        result.append(
            {
                "metric": metric,
                "positive": str(item.get("positive") or "").strip(),
                "neutral": str(item.get("neutral") or "").strip(),
                "negative": str(item.get("negative") or "").strip(),
            }
        )
    return result


def _normalize_visualizations(value: Any, metrics: list[str], dimensions: list[str]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    allowed_types = {"column", "line", "table"}
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        chart_type = _normalize_chart_type(item.get("type"))
        if chart_type not in allowed_types:
            continue
        metric = str(item.get("metric") or (metrics[0] if metrics else "metric_value")).strip()
        dimension = str(item.get("dimension") or (dimensions[0] if dimensions else "dimension_value")).strip()
        result.append(
            {
                "type": chart_type,
                "title": str(item.get("title") or f"{metric}按{dimension}分析").strip(),
                "dimension": dimension,
                "metric": metric,
                "purpose": str(item.get("purpose") or "展示实际查询结果").strip(),
            }
        )
    return result[:5]


def _normalize_chart_type(value: Any) -> str:
    chart_type = str(value or "").strip().lower()
    if chart_type == "bar":
        return "column"
    if chart_type in {"radar", "pie"}:
        return "table"
    return chart_type


def _safe_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _safe_model_context(model: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(model, dict):
        return None
    return {
        key: value
        for key, value in model.items()
        if key not in {"value", "apiKey", "secret", "token", "password"}
    }


def _scene_payload(request: IntelligentAnalysisRequest) -> dict[str, Any]:
    surface = request.surface_context if isinstance(request.surface_context, dict) else {}
    scene = surface.get("analysis_scene") if isinstance(surface.get("analysis_scene"), dict) else {}
    return scene


def _scene_prompt_context(request: IntelligentAnalysisRequest) -> dict[str, Any]:
    scene = _scene_payload(request)
    return {
        "surface": scene.get("surface") or "",
        "voice_mode": scene.get("voice_mode") or "",
        "analysis_kinds": scene.get("analysis_kinds") or [],
        "skill_ids": scene.get("skill_ids") or [],
        "dataset_scope": scene.get("dataset_scope") or "",
        "reason": scene.get("reason") or "",
    }


def _scene_kind_instructions(request: IntelligentAnalysisRequest) -> str:
    try:
        from backend.platform.kernel.scene import analysis_kind_instructions

        scene = _scene_payload(request)
        return analysis_kind_instructions(tuple(scene.get("analysis_kinds") or ()))
    except Exception:
        return "描述性分析：陈述现状、结构、分布、趋势、极值和异常，不解释因果。"


def _scene_approach_note(request: IntelligentAnalysisRequest) -> str:
    scene = _scene_payload(request)
    surface = str(scene.get("surface") or "")
    kinds = "、".join(str(item) for item in (scene.get("analysis_kinds") or ["descriptive"]))
    if surface == "chart_followup":
        location = "图表追问，仅使用当前图绑定数据集"
    elif surface == "page_rail":
        location = "整页 AI 分析，汇总当前页可视化数据"
    elif surface == "textbox_voice":
        location = "文本框实时语音仅转写，不进入分析运行时"
    else:
        location = "智能分析主查询"
    return f"场景：{location}。分析方法：{kinds}。{_scene_kind_instructions(request)}"


def _skill_label(request: IntelligentAnalysisRequest) -> str:
    names: list[str] = []
    if isinstance(request.skills, list):
        names.extend(str(skill.get("name") or "").strip() for skill in request.skills if isinstance(skill, dict))
    if request.skill:
        names.append(str(request.skill.get("name") or "").strip())
    return " + ".join(dict.fromkeys(name for name in names if name))


def _is_brief_follow_up(request: IntelligentAnalysisRequest) -> bool:
    policy = request.context_policy if isinstance(request.context_policy, dict) else {}
    surface = request.surface_context if isinstance(request.surface_context, dict) else {}
    if str(policy.get("resultFormat") or policy.get("result_format") or "").strip() == "brief_visual":
        return True
    scene = surface.get("analysis_scene") if isinstance(surface.get("analysis_scene"), dict) else {}
    hint = str(surface.get("analysis_scene_hint") or scene.get("surface") or "").strip()
    return hint in {"chart_followup", "page_rail"}


def _runtime_chain(
    request: IntelligentAnalysisRequest,
    planning: dict[str, Any],
    model_invocation: dict[str, Any],
) -> dict[str, Any]:
    scene = _scene_prompt_context(request)
    memories = (request.asset_context.get("analysis_memories") if isinstance(request.asset_context, dict) else []) or []
    skill_ids = [
        str(skill.get("id") or "").strip()
        for skill in request.skills
        if isinstance(skill, dict) and str(skill.get("id") or "").strip()
    ]
    skill_memories = [
        memory
        for skill in request.skills
        if isinstance(skill, dict)
        for memory in (skill.get("memories") or [])
        if isinstance(memory, dict)
    ]
    memory_ids = [
        str(memory.get("id") or "").strip()
        for memory in [*(memories if isinstance(memories, list) else []), *skill_memories]
        if isinstance(memory, dict) and str(memory.get("id") or "").strip()
    ]
    return {
        "version": "loan_analysis_runtime.v1",
        "engine": "IntelligentAnalysisEngine",
        "model_application_module": str(request.surface_context.get("model_application_module") or "intelligent_analysis_reasoning"),
        "dataset_scope": str(scene.get("dataset_scope") or "page"),
        "scene_intent": {
            "surface": str(scene.get("surface") or ""),
            "analysis_kinds": list(scene.get("analysis_kinds") or []),
        },
        "stages": [
            {"code": "scene_intent", "status": "completed"},
            {
                "code": "analysis_plan",
                "status": "completed",
                "source": str(planning.get("planning_source") or "deterministic"),
                "prompt_template_id": str((planning.get("planning_invocation") or {}).get("prompt_template_id") or PLANNING_PROMPT_TEMPLATE_ID),
            },
            {"code": "skill_dispatch", "status": "completed", "skill_ids": list(dict.fromkeys(skill_ids))},
            {"code": "memory_fusion", "status": "completed", "memory_ids": list(dict.fromkeys(memory_ids))},
            {"code": "evidence_query", "status": "completed", "row_count": len(request.query_result.get("data") or [])},
            {
                "code": "result_synthesis",
                "status": "completed" if model_invocation.get("status") in {"connected", "skipped"} else "fallback",
                "prompt_template_id": str(model_invocation.get("prompt_template_id") or ANALYSIS_PROMPT_TEMPLATE_ID),
            },
        ],
        "output_framework": "total_to_detail",
    }


def _infer_fields_from_rows(rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    if not rows:
        return [], []
    skip = {"_visual_source", "fieldLabels", "field_labels", "raw"}
    keys = [str(key) for key in rows[0].keys() if str(key) not in skip and not str(key).startswith("_")]
    metrics: list[str] = []
    dimensions: list[str] = []
    for key in keys:
        numeric = sum(1 for row in rows if _safe_number(row.get(key)) is not None)
        if numeric >= max(1, (len(rows) + 1) // 2):
            metrics.append(key)
        else:
            dimensions.append(key)
    time_dims = [item for item in dimensions if _is_time_field_name(item)]
    dimensions = time_dims + [item for item in dimensions if item not in time_dims]
    return metrics, dimensions


def _field_labels_from_rows(rows: list[dict[str, Any]]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for row in rows[:8]:
        raw = row.get("fieldLabels") or row.get("field_labels")
        if isinstance(raw, dict):
            for key, value in raw.items():
                name = str(value or "").strip()
                if name:
                    labels[str(key)] = name
    return labels


def _is_time_field_name(name: str) -> bool:
    lowered = str(name or "").strip().lower()
    return any(token in lowered for token in ("month", "date", "week", "year", "day", "time", "月份", "日期", "周"))


def _brief_time_highlights(
    rows: list[dict[str, Any]],
    metric: str,
    metric_label: str,
    time_dim: str,
    category_dim: str,
    labels: dict[str, str],
) -> list[str]:
    groups: dict[str, list[tuple[str, float]]] = {}
    for row in rows:
        value = _safe_number(row.get(metric))
        time_value = str(row.get(time_dim) or "").strip()
        if value is None or not time_value:
            continue
        category = str(row.get(category_dim) or "").strip() if category_dim else ""
        groups.setdefault(category or "总体", []).append((time_value, value))
    highlights: list[str] = []
    for category, points in list(groups.items())[:3]:
        ordered = sorted(points, key=lambda item: item[0])
        start_label, start_value = ordered[0]
        end_label, end_value = ordered[-1]
        prefix = f"{category}的" if category_dim and category not in {"", "总体"} else ""
        if start_label == end_label:
            highlights.append(f"{prefix}{metric_label}在{end_label}为{_format_brief_number(end_value, metric)}")
            continue
        direction = "升至" if end_value > start_value else "降至" if end_value < start_value else "仍为"
        highlights.append(
            f"{prefix}{metric_label}从{start_label}的{_format_brief_number(start_value, metric)}{direction}{end_label}的{_format_brief_number(end_value, metric)}"
        )
    return highlights


def _brief_rank_highlights(
    rows: list[dict[str, Any]],
    metric: str,
    metric_label: str,
    category_dim: str,
    labels: dict[str, str],
) -> list[str]:
    scored = []
    for row in rows:
        value = _safe_number(row.get(metric))
        if value is None:
            continue
        name = str(row.get(category_dim) or "").strip() if category_dim else ""
        scored.append((name or "该分组", value))
    if not scored:
        return []
    top_name, top_value = max(scored, key=lambda item: item[1])
    bottom_name, bottom_value = min(scored, key=lambda item: item[1])
    if top_name == bottom_name or top_value == bottom_value:
        return [f"{metric_label}为{_format_brief_number(top_value, metric)}"]
    dimension_label = _human_field_label(category_dim, labels) if category_dim else "分组"
    return [
        f"{metric_label}最高为{dimension_label}{top_name} {_format_brief_number(top_value, metric)}，最低为{bottom_name} {_format_brief_number(bottom_value, metric)}"
    ]


def _human_field_label(name: str, labels: dict[str, str] | None = None) -> str:
    if labels and labels.get(name):
        return str(labels[name])
    defaults = {
        "m1_overdue_rate": "M1逾期率",
        "loan_balance": "在贷余额",
        "loan_amount": "放款金额",
        "drawdown_rate": "动支率",
        "conversion_rate": "转化率",
        "active_customer_count": "活跃客户数",
        "product_line": "产品线",
        "branch_name": "机构",
        "month": "月份",
        "customer_segment": "客群",
    }
    raw = str(name or "").strip()
    if raw in defaults:
        return defaults[raw]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+", raw):
        return raw
    token_labels = {
        "active": "活跃", "amount": "金额", "approval": "审批", "average": "平均", "avg": "平均",
        "balance": "余额", "branch": "机构", "channel": "渠道", "completion": "完成", "count": "数量",
        "customer": "客户", "date": "日期", "day": "日", "drawdown": "动支", "gap": "差异",
        "id": "编号", "line": "线", "loan": "贷款", "metric": "指标", "month": "月份",
        "name": "名称", "order": "顺序", "overdue": "逾期", "product": "产品", "rate": "率",
        "ratio": "占比", "risk": "风险", "segment": "客群", "stage": "阶段", "stat": "统计",
        "target": "目标", "total": "总计", "value": "数值", "week": "周", "year": "年度",
    }
    translated: list[str] = []
    unknown = False
    for token in raw.lower().split("_"):
        label = token_labels.get(token)
        if label:
            translated.append(label)
        elif re.fullmatch(r"m\d+", token):
            translated.append(token.upper())
        else:
            unknown = True
    if not translated:
        return "业务字段"
    label = "".join(translated)
    return f"{label}相关字段" if unknown else label


def _format_brief_number(value: float, metric_name: str) -> str:
    lowered = str(metric_name or "").lower()
    rate_like = any(token in lowered for token in ("rate", "ratio", "逾期", "占比", "转化", "yield"))
    if rate_like and abs(value) <= 2:
        percent = value * 100 if abs(value) <= 1 else value
        return f"{percent:.2f}%"
    if abs(value) >= 1e8:
        return f"{value / 1e8:.1f}亿"
    if abs(value) >= 1e4:
        return f"{value / 1e4:.1f}万"
    if abs(value) >= 100:
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def _build_model_context_brief(request: IntelligentAnalysisRequest) -> str:
    skill_names = _skill_label(request) or "未显式选择Skill"
    files = [
        str(file.get("name") or file.get("id") or "").strip()
        for file in request.files
        if isinstance(file, dict) and str(file.get("name") or file.get("id") or "").strip()
    ]
    selected_tables = request.asset_context.get("selected_data_tables") if isinstance(request.asset_context, dict) else []
    related_tables = request.asset_context.get("related_detail_tables") if isinstance(request.asset_context, dict) else []
    table_names = [
        str(table.get("name") or table.get("code") or "").strip()
        for table in selected_tables
        if isinstance(table, dict) and str(table.get("name") or table.get("code") or "").strip()
    ]
    topics = request.asset_context.get("topics") if isinstance(request.asset_context, dict) else []
    topic_names = [
        str(topic.get("name") or topic.get("code") or "").strip()
        for topic in topics
        if isinstance(topic, dict) and str(topic.get("name") or topic.get("code") or "").strip()
    ]
    related_names = [
        str(table.get("name") or table.get("tableNameCn") or table.get("code") or table.get("tableNameEn") or "").strip()
        for table in related_tables
        if isinstance(table, dict)
    ]
    analysis_memories = request.asset_context.get("analysis_memories") if isinstance(request.asset_context, dict) else []
    memory_names = [
        str(memory.get("title") or memory.get("name") or memory.get("purpose") or memory.get("id") or "").strip()
        for memory in analysis_memories
        if isinstance(memory, dict) and str(memory.get("title") or memory.get("name") or memory.get("purpose") or memory.get("id") or "").strip()
    ]
    turn_count = request.conversation_context.get("turn_count") if isinstance(request.conversation_context, dict) else 0
    policy = request.context_policy if isinstance(request.context_policy, dict) else {}
    return "；".join(
        [
            f"触发方式={request.analysis_trigger}",
            f"Skill={skill_names}",
            f"上传文件={','.join(files) if files else '无'}",
            f"用户选择数据表={','.join(table_names) if table_names else '未手动选择'}",
            f"关联明细表={','.join(related_names) if related_names else '没有更细粒度数据，请关联明细数据'}",
            f"语义匹配主题表={','.join(topic_names) if topic_names else '未匹配'}",
            f"指定分析记忆={','.join(memory_names) if memory_names else '未指定'}",
            f"会话轮次={turn_count or 0}",
            f"策略={policy or '默认智能分析策略'}",
        ]
    )


def _model_input_context_for_prompt(request: IntelligentAnalysisRequest) -> dict[str, Any]:
    """Bounded, credential-free projection of everything added to the input box."""

    selected_tables = request.asset_context.get("selected_data_tables") if isinstance(request.asset_context, dict) else []
    related_tables = request.asset_context.get("related_detail_tables") if isinstance(request.asset_context, dict) else []
    table_context = [
        {
            "id": str(table.get("id") or "")[:160],
            "kind": str(table.get("kind") or "")[:40],
            "name": str(table.get("name") or "")[:240],
            "code": str(table.get("code") or "")[:240],
            "dataset_id": str(table.get("datasetId") or "")[:240],
            "source": str(table.get("source") or "")[:500],
            "row_count": int(table.get("rowCount") or 0),
            "quality_report": str(table.get("qualityReport") or "")[:500],
            "csv_path": str(table.get("csvPath") or "")[:500],
            "description": str(table.get("description") or "")[:1200],
            "positioning": str(table.get("tableType") or table.get("positioning") or table.get("applicableScene") or "")[:500],
            "restrictions": str(table.get("restrictions") or "")[:1000],
            "fields": [
                {
                    key: field.get(key)
                    for key in ("fieldNameEn", "fieldNameCn", "type", "explanation", "metricCode", "metricLogic")
                    if field.get(key) not in (None, "")
                }
                for field in (table.get("fields") or [])[:50]
                if isinstance(field, dict)
            ] if isinstance(table.get("fields"), list) else str(table.get("fields") or "")[:4000],
            "sql": str(table.get("sql") or "")[:6000],
        }
        for table in (selected_tables or [])[:8]
        if isinstance(table, dict)
    ]
    file_context = [
        {
            "id": str(file.get("id") or "")[:160],
            "name": str(file.get("name") or "")[:240],
            "type": str(file.get("type") or "")[:120],
            "content_preview": str(file.get("contentPreview") or file.get("content_preview") or "")[:4000],
        }
        for file in request.files[:8]
        if isinstance(file, dict)
    ]
    skills = []
    for skill in [*request.skills, *([request.skill] if request.skill else [])]:
        if not isinstance(skill, dict):
            continue
        projected_skill = {
            "id": str(skill.get("id") or "")[:160],
            "name": str(skill.get("name") or "")[:240],
            "category": str(skill.get("category") or "")[:80],
            "description": str(skill.get("description") or "")[:1200],
            "memory_refs": [str(item)[:160] for item in (skill.get("memoryRefs") or [])[:20]],
            "tool_refs": [str(item)[:160] for item in (skill.get("toolRefs") or [])[:20]],
            "analysis_method": str(skill.get("analysisMethod") or "")[:2400],
            "document_abstraction": str(skill.get("documentAbstraction") or "")[:2400],
            "viewpoint_strategy": str(skill.get("viewpointStrategy") or "")[:2400],
            "recommended_skill_ids": [str(item)[:160] for item in (skill.get("recommendedSkillIds") or [])[:20]],
            "memories": [dict(item) for item in (skill.get("memories") or [])[:12] if isinstance(item, dict)],
            "tools": [dict(item) for item in (skill.get("tools") or [])[:12] if isinstance(item, dict)],
        }
        if str(skill.get("category") or "") != "主题":
            projected_skill["output_format"] = str(skill.get("outputFormat") or "")[:2400]
        skills.append(projected_skill)
        if len(skills) >= 12:
            break
    turns = request.conversation_context.get("turns") if isinstance(request.conversation_context, dict) else []
    conversation = [
        {
            "role": str(turn.get("role") or "")[:20],
            "content": str(turn.get("content") or "")[:1600],
        }
        for turn in (turns or [])[-8:]
        if isinstance(turn, dict)
    ]
    return {
        "trigger": request.analysis_trigger,
        "question": request.question[:4000],
        "skills": skills,
        "external_tools": [
            {
                key: plugin.get(key)
                for key in ("id", "name", "provider", "toolType", "description", "capabilities", "status")
                if plugin.get(key) not in (None, "")
            }
            for plugin in request.plugins[:12]
            if isinstance(plugin, dict)
        ],
        "uploaded_documents": file_context,
        "selected_data_sources": table_context,
        "related_detail_sources": [
            {
                "id": str(table.get("id") or "")[:160],
                "name": str(table.get("name") or table.get("tableNameCn") or "")[:240],
                "code": str(table.get("code") or table.get("tableNameEn") or "")[:240],
                "fields": table.get("fields") if isinstance(table.get("fields"), list) else str(table.get("fields") or "")[:4000],
            }
            for table in (related_tables or [])[:4]
            if isinstance(table, dict)
        ],
        "detail_analysis_instruction": (
            "先分析当前可视化数据表的全量维度与指标组合，再分析关联明细表。"
            if related_tables
            else "没有更细粒度数据，请关联明细数据"
        ),
        "analysis_memories": [
            {
                key: memory.get(key)
                for key in (
                    "id", "title", "name", "scenario", "purpose", "description", "keywords",
                    "steps", "analysisSteps", "rules", "commonConclusions", "riskTips",
                    "habitType", "behaviorDetail", "evidence", "relatedMetrics", "weight",
                )
                if memory.get(key) not in (None, "")
            }
            for memory in (
                request.asset_context.get("analysis_memories", [])
                if isinstance(request.asset_context, dict)
                else []
            )[:12]
            if isinstance(memory, dict)
        ],
        "metric_dictionary_definitions": [
            dict(metric)
            for metric in (
                request.asset_context.get("metric_dictionary_definitions", [])
                if isinstance(request.asset_context, dict)
                else []
            )[:20]
            if isinstance(metric, dict)
        ],
        "conclusion_generation_rules": [
            {
                key: rule.get(key)
                for key in ("id", "name", "datasetId", "datasetName", "skillId", "metricRules")
                if rule.get(key) not in (None, "")
            }
            for rule in (
                request.asset_context.get("conclusion_rules", [])
                if isinstance(request.asset_context, dict)
                else []
            )[:24]
            if isinstance(rule, dict)
        ],
        "reviewed_workflow_memories": [
            {
                key: memory.get(key)
                for key in ("memory_id", "memory_type", "title", "content", "confidence")
                if memory.get(key) not in (None, "")
            }
            for memory in (request.analysis_plan.get("memory_refs") or [])[:10]
            if isinstance(memory, dict)
        ],
        "matched_intents": [
            {
                key: intent.get(key)
                for key in ("id", "name", "purpose", "description", "keywords", "relatedTopic", "relatedExperience")
                if intent.get(key) not in (None, "")
            }
            for intent in (
                request.asset_context.get("matched_intents", [])
                if isinstance(request.asset_context, dict)
                else []
            )[:6]
            if isinstance(intent, dict)
        ],
        "reviewed_analysis_experiences": [
            {
                key: experience.get(key)
                for key in ("id", "name", "title", "purpose", "description", "steps", "rules", "commonConclusions", "riskTips")
                if experience.get(key) not in (None, "")
            }
            for experience in (
                request.asset_context.get("experiences", [])
                if isinstance(request.asset_context, dict)
                else []
            )[:6]
            if isinstance(experience, dict)
        ],
        # Page state helps the model understand what the user is looking at,
        # but it is never authoritative evidence.  The prompts below require
        # every factual claim to come from the executed query evidence.
        "current_page_context_untrusted": _bounded_surface_context(request.surface_context),
        "governed_metric_definitions": [
            dict(metric)
            for metric in (request.analysis_plan.get("metric_definitions") or [])[:20]
            if isinstance(metric, dict)
        ],
        "plugins": [
            {
                "id": str(plugin.get("id") or "")[:160],
                "name": str(plugin.get("name") or "")[:240],
            }
            for plugin in request.plugins[:8]
            if isinstance(plugin, dict)
        ],
        "conversation": conversation,
        "policy": request.context_policy,
    }


def _bounded_surface_context(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {
        "route", "page_key", "page_title", "selected_institution", "filters",
        "selected_data_point", "visualization", "dataset_snapshot", "evidence_refs",
        "artifact_id", "analysis_plan_hint",
    }
    bounded: dict[str, Any] = {}
    for key in allowed:
        item = value.get(key)
        if item in (None, "", [], {}):
            continue
        serialized = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        if len(serialized) <= 12_000:
            bounded[key] = item
    return bounded


def _metric_expression(metric: str, index: int = 0) -> str:
    alias = "metric_value" if index == 0 else metric
    lowered = metric.lower()
    if "rate" in lowered or "率" in metric:
        return f"SUM({metric}_numerator) / NULLIF(SUM({metric}_denominator), 0) AS {alias}"
    if lowered == "roi":
        return "SUM(roi_numerator) / NULLIF(SUM(roi_denominator), 0) AS " + alias
    if "amount" in lowered or "balance" in lowered or "金额" in metric or "余额" in metric:
        return f"SUM({metric}) AS {alias}"
    return f"SUM({metric}) AS {alias}"


def _summarize_group_names(names: list[str], limit: int = 3) -> str:
    visible = names[:limit]
    label = "、".join(visible) if visible else "未命名分组"
    if len(names) > limit:
        return f"{label} 等 {len(names)} 个分组"
    return label


def _safe_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _query_evidence_for_prompt(query_result: dict[str, Any]) -> str:
    rows = query_result.get("data") if isinstance(query_result.get("data"), list) else []
    semantic_info = query_result.get("semantic_info") if isinstance(query_result.get("semantic_info"), dict) else {}
    evidence = query_result.get("evidence") if isinstance(query_result.get("evidence"), dict) else {}
    safe_payload = {
        "evidence_id": evidence.get("evidence_id"),
        "executed_sql": str(evidence.get("executed_sql") or "")[:4_000],
        "execution_statement": str(evidence.get("execution_statement") or "")[:4_000],
        "sql_executed": bool(evidence.get("sql_executed")),
        "parameters": query_result.get("parameters") if isinstance(query_result.get("parameters"), dict) else {},
        "semantic_info": {
            "dataset_id": semantic_info.get("dataset_id"),
            "schema_mapping": semantic_info.get("schema_mapping"),
            "data_source": semantic_info.get("data_source"),
            "aggregation": semantic_info.get("aggregation"),
            "aggregations": semantic_info.get("aggregations"),
            "totals": semantic_info.get("totals"),
            "full_group_count": semantic_info.get("full_group_count"),
            "summary_complete": semantic_info.get("summary_complete"),
            "metric_definitions_bound": semantic_info.get("metric_definitions_bound"),
            "source_snapshot": semantic_info.get("source_snapshot"),
            "row_count": len(rows),
        },
        "rows": [dict(row) for row in rows[:20] if isinstance(row, dict)],
    }
    return json.dumps(safe_payload, ensure_ascii=False, sort_keys=True)


def _quote_known_tables(sql: str) -> str:
    return (
        sql.replace('FROM "loan_operation_fact"', 'FROM "loan_operation_fact"')
        .replace('from "loan_operation_fact"', 'from "loan_operation_fact"')
        .replace("FROM loan_operation_fact", 'FROM "loan_operation_fact"')
        .replace("from loan_operation_fact", 'from "loan_operation_fact"')
    )
