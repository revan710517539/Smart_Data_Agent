from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from backend.platform.data_processing import PythonSandbox
from backend.platform.security.sql_validation import validate_read_only_sql_candidate
from backend.platform.settings import call_model_text_completion


PLANNING_PROMPT_TEMPLATE_ID = "intelligent_analysis.bank_operating.plan.v2"
ANALYSIS_PROMPT_TEMPLATE_ID = "intelligent_analysis.bank_operating.final.v2"


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
        fallback_conclusions = self._build_conclusions(request, skill_name)
        fallback_summary = "\n".join(fallback_conclusions)
        visualization_suggestions = list(planning.get("visualization_suggestions") or self._build_visualization_suggestions(request))
        final_payload = {
            "analysis_summary": fallback_summary,
            "conclusions": fallback_conclusions,
            "metric_findings": [],
            "visualization_suggestions": visualization_suggestions,
            "conclusion_coverage": self._build_conclusion_coverage(request),
        }
        if not isinstance(request.model, dict) or not request.model.get("id"):
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
                    final_payload = _normalize_final_payload(payload, final_payload)
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
                            final_payload = _normalize_final_payload(payload, final_payload)
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
    processed = []
    metrics = context.get("metrics", [])
    for row in data:
        item = dict(row)
        for metric in metrics:
            item[metric] = round(float(row.get(metric, 0) or 0), 6)
        processed.append(item)
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
        chart_types = list(dict.fromkeys(
            _normalize_chart_type(chart_type)
            for chart_type in (_safe_list(request.analysis_plan.get("chart_types")) or ["column", "table"])
        ))
        dimensions = _safe_list(request.analysis_plan.get("dimensions")) or ["branch_name", "product_line"]
        metrics = _safe_list(request.analysis_plan.get("metrics")) or ["metric_value"]
        suggestions: list[dict[str, Any]] = []
        for index, chart_type in enumerate(chart_types[:3]):
            if chart_type == "line":
                purpose = "观察指标随统计周期的连续变化、拐点和异常波动。"
            elif chart_type == "table":
                purpose = "保留多维明细字段，支持交叉查看、二次下钻和人工核对。"
            else:
                purpose = "比较不同维度下的指标规模、排名和贡献。"
            suggestions.append(
                {
                    "type": chart_type,
                    "title": f"{metrics[0]}按{dimensions[index % len(dimensions)]}分析",
                    "dimension": dimensions[index % len(dimensions)],
                    "metric": metrics[min(index, len(metrics) - 1)],
                    "purpose": purpose,
                }
            )
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
        return [
            trigger_note,
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
    return f"""你是银行数据分析规划模型。第一阶段只做问题理解和可执行规划，不得编造实际数据结论。
问题：{request.question}
分析场景：{skill_name or '通用智能分析'}
输入框完整上下文：{json.dumps(_model_input_context_for_prompt(request), ensure_ascii=False, sort_keys=True, default=str)}
服务端允许的分析计划：{json.dumps(safe_plan, ensure_ascii=False, sort_keys=True, default=str)}

请返回且只返回一个 JSON 对象，结构必须完全匹配：
{json.dumps(schema, ensure_ascii=False, sort_keys=True)}

约束：
1. metrics、dimensions 只能选择服务端允许清单中的值，不得创建新口径。
2. SQL 只能是一条只读 SELECT/WITH；禁止 DDL、DML、多语句和危险函数，并保留租户与时间参数。
3. 两段 Python 都禁止 import、文件、网络、反射和动态执行；数据加工只能定义 process_data(data, context)，可视化只能定义 build_chart(data, context)，并返回 JSON 可序列化对象。
4. metric_scenarios 必须穷举每个选中指标的较好、平稳、较差三类表现及分析方向，但不得声称这些情景已经发生。
5. 总 JSON 不超过 9000 个字符；两段 Python 各不超过 900 个字符且不要注释；分析步骤最多6条，情景文字每项不超过60个汉字，可视化建议最多3项。
6. 不要输出 Markdown、解释性前后缀或代码围栏。"""


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
    return f"""你是银行经营分析模型。现在执行第二阶段：把第一阶段规划和实际取数证据一起分析，生成最终页面结果。
问题：{request.question}
分析场景：{skill_name or '通用智能分析'}
输入框完整上下文：{json.dumps(_model_input_context_for_prompt(request), ensure_ascii=False, sort_keys=True, default=str)}
第一阶段规划：{json.dumps(safe_planning, ensure_ascii=False, sort_keys=True, default=str)}
实际执行证据：{_query_evidence_for_prompt(request.query_result)}

请返回且只返回一个 JSON 对象，结构必须完全匹配：
{json.dumps(schema, ensure_ascii=False, sort_keys=True)}

约束：
1. 只能依据实际执行证据陈述事实；没有返回的指标必须明确写“未返回”，不得套用情景结论冒充事实。
2. 每条结论必须可追溯到证据ID、字段、汇总值或返回行。
3. visualization_suggestions 只能使用 line、column、table，并根据时间趋势、维度对比或多维明细主题绑定实际返回的指标和维度。
4. 对每个返回指标都要覆盖总体值、头部、尾部、零值/异常值；对每个返回维度说明已覆盖范围，无法从证据判断的原因必须列入 limitations。
5. analysis_summary 必须包含核心结论、数据证据、原因边界、经营建议、风险提示和后续动作。
6. 不要输出 Markdown、解释性前后缀或代码围栏。"""


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


def _normalize_final_payload(payload: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    conclusions = _safe_list(payload.get("conclusions"))[:20] or list(fallback["conclusions"])
    summary = str(payload.get("analysis_summary") or "").strip() or "\n".join(conclusions)
    findings = [
        {
            "metric": str(item.get("metric") or "").strip(),
            "observed": str(item.get("observed") or "").strip(),
            "interpretation": str(item.get("interpretation") or "").strip(),
            "evidence": str(item.get("evidence") or "").strip(),
        }
        for item in (payload.get("metric_findings") or [])
        if isinstance(item, dict) and str(item.get("metric") or "").strip()
    ][:20]
    visualizations = _normalize_visualizations(payload.get("visualization_suggestions"), [], [])
    return {
        "analysis_summary": summary[:12_000],
        "conclusions": conclusions,
        "metric_findings": findings,
        "visualization_suggestions": visualizations or list(fallback["visualization_suggestions"]),
        # Coverage is computed from executed evidence, never trusted from the
        # language model.  This makes exhaustiveness auditable and deterministic.
        "conclusion_coverage": dict(fallback.get("conclusion_coverage") or {}),
    }


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


def _skill_label(request: IntelligentAnalysisRequest) -> str:
    names: list[str] = []
    if isinstance(request.skills, list):
        names.extend(str(skill.get("name") or "").strip() for skill in request.skills if isinstance(skill, dict))
    if request.skill:
        names.append(str(request.skill.get("name") or "").strip())
    return " + ".join(dict.fromkeys(name for name in names if name))


def _build_model_context_brief(request: IntelligentAnalysisRequest) -> str:
    skill_names = _skill_label(request) or "未显式选择Skill"
    files = [
        str(file.get("name") or file.get("id") or "").strip()
        for file in request.files
        if isinstance(file, dict) and str(file.get("name") or file.get("id") or "").strip()
    ]
    selected_tables = request.asset_context.get("selected_data_tables") if isinstance(request.asset_context, dict) else []
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
            f"语义匹配主题表={','.join(topic_names) if topic_names else '未匹配'}",
            f"指定分析记忆={','.join(memory_names) if memory_names else '未指定'}",
            f"会话轮次={turn_count or 0}",
            f"策略={policy or '默认智能分析策略'}",
        ]
    )


def _model_input_context_for_prompt(request: IntelligentAnalysisRequest) -> dict[str, Any]:
    """Bounded, credential-free projection of everything added to the input box."""

    selected_tables = request.asset_context.get("selected_data_tables") if isinstance(request.asset_context, dict) else []
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
