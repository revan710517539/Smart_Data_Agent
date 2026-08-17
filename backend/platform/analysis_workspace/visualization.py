from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .models import VisualizationSpec


ALLOWED_CHART_TYPES = {
    "kpi", "line", "area", "bar", "column", "stacked_bar", "combo", "donut",
    "scatter", "funnel", "treemap", "radar", "table", "pivot",
}


class VisualizationPlanner:
    """Deterministic chart selection after a model proposes analysis intent."""

    def plan(
        self,
        *,
        question: str,
        rows: list[dict[str, Any]],
        dimensions: list[str],
        metrics: list[str],
        intent: dict[str, Any] | None = None,
        proposed_chart_types: list[str] | None = None,
        requested_chart_types: list[str] | None = None,
    ) -> VisualizationSpec:
        normalized_rows = [row for row in rows if isinstance(row, dict)]
        dimension_fields = [field for field in dimensions if _field_exists(normalized_rows, field)]
        metric_fields = [field for field in metrics if _numeric_field(normalized_rows, field)]
        primary_intent = str((intent or {}).get("primary_intent") or "").lower()
        question_text = question.lower()
        time_fields = [field for field in dimension_fields if _time_field(normalized_rows, field)]
        category_count = _category_count(normalized_rows, dimension_fields[0]) if dimension_fields else 0
        point_count = len(normalized_rows)

        chart_type, reason, alternatives = self._choose(
            primary_intent=primary_intent,
            question=question_text,
            point_count=point_count,
            category_count=category_count,
            dimensions=dimension_fields,
            metrics=metric_fields,
            time_fields=time_fields,
        )
        requested = [item for item in (requested_chart_types or []) if item in ALLOWED_CHART_TYPES]
        compatible_request = next((item for item in requested if _chart_is_compatible(item, dimension_fields, metric_fields, point_count)), None)
        if compatible_request:
            alternatives = list(dict.fromkeys([chart_type, *alternatives]))
            chart_type = compatible_request
            reason = "用户明确指定可视化样式；字段与数据量校验通过，按用户要求呈现"
        elif requested:
            reason += "；用户指定样式与当前字段不兼容，已安全回退"
        proposed = [item for item in (proposed_chart_types or []) if item in ALLOWED_CHART_TYPES]
        if proposed and proposed[0] == chart_type:
            reason += "；模型候选通过字段和可读性校验"

        x = time_fields[0] if time_fields else (dimension_fields[0] if dimension_fields else "")
        orientation = "horizontal" if chart_type == "bar" and category_count > 6 else "vertical"
        pivot = None
        if chart_type == "pivot":
            pivot = {
                "row_dimensions": dimension_fields[:1],
                "column_dimensions": dimension_fields[1:2],
                "metrics": metric_fields[:8],
                "subtotals": True,
                "grand_total": True,
                "freeze_rows": 1,
                "freeze_columns": max(1, len(dimension_fields[:1])),
            }
        return VisualizationSpec(
            chart_type=chart_type,
            title=_title(question),
            x=x,
            y=tuple(metric_fields[:8]),
            series=dimension_fields[1] if len(dimension_fields) > 1 else "",
            orientation=orientation,
            reason=reason,
            alternatives=tuple(alternatives),
            pivot=pivot,
        )

    @staticmethod
    def _choose(*, primary_intent: str, question: str, point_count: int, category_count: int, dimensions: list[str], metrics: list[str], time_fields: list[str]) -> tuple[str, str, list[str]]:
        if not metrics:
            return "table", "没有可安全聚合的数值指标，使用明细表避免误导", []
        if len(dimensions) >= 2 and len(metrics) >= 2 and (point_count > 100 or "汇总" in question or "交叉" in question):
            return "pivot", "多维多指标汇总使用交叉表，保留精确值和层级", ["table", "stacked_bar"]
        if "漏斗" in question or "转化" in question or primary_intent == "funnel":
            return "funnel", "问题描述阶段转化过程，使用漏斗呈现流失", ["bar", "table"]
        if "相关" in question or "关系" in question or "离群" in question or primary_intent in {"correlation", "outlier"}:
            if len(metrics) >= 2:
                return "scatter", "两个数值指标需要观察相关性和离群点", ["table"]
        if point_count == 1 or (not dimensions and len(metrics) == 1):
            return "kpi", "单一结果适合用核心指标卡直接表达", ["table"]
        if time_fields:
            if len(metrics) > 1:
                return "combo", "多个指标沿时间变化，组合图便于比较趋势", ["line", "table"]
            return "line", "连续时间序列使用折线图展示趋势", ["area", "table"]
        if "占比" in question or "构成" in question or primary_intent == "composition":
            if 1 < category_count <= 5:
                return "donut", "类别较少且问题关注构成，可使用克制的环形图", ["stacked_bar", "table"]
            return "stacked_bar", "类别较多时堆叠条形图比饼图更易比较", ["bar", "table"]
        if "层级" in question or "贡献" in question or primary_intent in {"hierarchy", "contribution"}:
            return "treemap", "层级贡献使用树图表达面积占比和主要贡献项", ["bar", "table"]
        if "能力" in question and 3 <= len(metrics) <= 6 and category_count <= 5:
            return "radar", "有限维度能力比较适合雷达图", ["bar", "table"]
        if category_count > 40 or point_count > 500:
            return "table", "类别或数据点过多，图表会拥挤，回退为可排序表格", ["bar"]
        return "bar", "分类比较和排名使用条形图最清晰", ["table"]


def _field_exists(rows: list[dict[str, Any]], field: str) -> bool:
    return bool(field) and any(field in row for row in rows)


def _chart_is_compatible(chart_type: str, dimensions: list[str], metrics: list[str], point_count: int) -> bool:
    if chart_type == "table":
        return point_count > 0
    if chart_type == "pivot":
        return len(dimensions) >= 2 and bool(metrics)
    if chart_type == "scatter":
        return len(metrics) >= 2
    if chart_type == "kpi":
        return bool(metrics)
    if chart_type in {"radar", "donut", "funnel", "treemap", "line", "area", "bar", "column", "stacked_bar", "combo"}:
        return bool(dimensions) and bool(metrics)
    return False


def _numeric_field(rows: list[dict[str, Any]], field: str) -> bool:
    values = [row.get(field) for row in rows if row.get(field) not in {None, ""}]
    if not values:
        return False
    valid = 0
    for value in values[:100]:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            valid += 1
            continue
        try:
            float(str(value).replace(",", ""))
            valid += 1
        except ValueError:
            pass
    return valid / min(len(values), 100) >= 0.9


def _time_field(rows: list[dict[str, Any]], field: str) -> bool:
    lowered = field.lower()
    if any(token in lowered for token in ("date", "time", "month", "week", "year", "日期", "时间", "月份", "周")):
        return True
    values = [row.get(field) for row in rows if row.get(field) not in {None, ""}][:20]
    if not values:
        return False
    return sum(_is_time(value) for value in values) / len(values) >= 0.8


def _is_time(value: Any) -> bool:
    if isinstance(value, (date, datetime)):
        return True
    text = str(value)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _category_count(rows: list[dict[str, Any]], field: str) -> int:
    return len({str(row.get(field)) for row in rows if row.get(field) not in {None, ""}})


def _title(question: str) -> str:
    value = " ".join(question.strip().split())
    return value[:60] or "可视化分析"
