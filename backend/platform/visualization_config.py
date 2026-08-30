from __future__ import annotations

import math
import re
from typing import Any


_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_RANK_DIRECTIONS = frozenset({"desc", "asc"})
_ASSOCIATION_SOURCES = frozenset({"metric", "progress"})
_ASSOCIATION_OPERATORS = frozenset({"gt", "gte", "eq", "lte", "lt"})
_ASSOCIATION_STYLES = frozenset({"background", "text", "value"})
_PROGRESS_DENOMINATOR_MODES = frozenset({"selected_row", "column_max"})
_TABLE_FONTS = frozenset({"system", "humanist", "serif", "mono"})
_TABLE_DENSITIES = frozenset({"compact", "comfortable"})
_CHART_FONTS = frozenset({"system", "humanist", "mono"})
_CHART_HEIGHTS = frozenset({"compact", "standard", "expanded"})
_CHART_BAR_WIDTHS = frozenset({"slim", "standard", "wide"})
_DEFAULT_TABLE_STYLE = {
    "templateId": "sda-clean",
    "headerBackground": "#F5FAF7",
    "headerTextColor": "#536B5E",
    "headerBorderColor": "#DCE7DF",
    "bodyBackground": "#FFFFFF",
    "alternateRowBackground": "#F8FBF9",
    "bodyTextColor": "#343B37",
    "borderColor": "#E7ECE9",
    "accentColor": "#3F8F68",
    "totalBackground": "#EAF3EE",
    "totalTextColor": "#294E3B",
    "fontFamily": "system",
    "density": "comfortable",
    "bandedRows": True,
    "emphasizeFirstColumn": False,
}
_DEFAULT_CHART_STYLE = {
    "templateId": "chart-jade",
    "backgroundColor": "#FBFDFC",
    "plotBackgroundColor": "#FFFFFF",
    "textColor": "#34443C",
    "mutedTextColor": "#7F8F87",
    "gridColor": "#E7EEE9",
    "axisColor": "#CFDAD3",
    "palette": ["#287557", "#5F8173", "#617988", "#84958B", "#526F65", "#A18B62", "#8C9992", "#A1ABA5"],
    "fontFamily": "system",
    "chartHeight": "standard",
    "lineWidth": 2.0,
    "pointRadius": 2.5,
    "barRadius": 4.0,
    "barWidth": "standard",
    "areaOpacity": 0.1,
}


def _bounded_text(value: Any, width: int) -> str:
    return str(value or "").strip()[:width]


def _single_value_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    for item in value:
        text = _bounded_text(item, 500)
        if text:
            return [text]
    return []


def _color(value: Any, fallback: str) -> str:
    candidate = _bounded_text(value, 7)
    return candidate.upper() if _HEX_COLOR.fullmatch(candidate) else fallback


def normalize_table_style(value: Any) -> dict[str, Any]:
    """Bound the table presentation token set without persisting table data."""
    if not isinstance(value, dict):
        return {}
    template_id = _bounded_text(value.get("templateId"), 120) or _DEFAULT_TABLE_STYLE["templateId"]
    return {
        "templateId": template_id,
        "headerBackground": _color(value.get("headerBackground"), _DEFAULT_TABLE_STYLE["headerBackground"]),
        "headerTextColor": _color(value.get("headerTextColor"), _DEFAULT_TABLE_STYLE["headerTextColor"]),
        "headerBorderColor": _color(value.get("headerBorderColor"), _DEFAULT_TABLE_STYLE["headerBorderColor"]),
        "bodyBackground": _color(value.get("bodyBackground"), _DEFAULT_TABLE_STYLE["bodyBackground"]),
        "alternateRowBackground": _color(value.get("alternateRowBackground"), _DEFAULT_TABLE_STYLE["alternateRowBackground"]),
        "bodyTextColor": _color(value.get("bodyTextColor"), _DEFAULT_TABLE_STYLE["bodyTextColor"]),
        "borderColor": _color(value.get("borderColor"), _DEFAULT_TABLE_STYLE["borderColor"]),
        "accentColor": _color(value.get("accentColor"), _DEFAULT_TABLE_STYLE["accentColor"]),
        "totalBackground": _color(value.get("totalBackground"), _DEFAULT_TABLE_STYLE["totalBackground"]),
        "totalTextColor": _color(value.get("totalTextColor"), _DEFAULT_TABLE_STYLE["totalTextColor"]),
        "fontFamily": _bounded_text(value.get("fontFamily"), 20) if _bounded_text(value.get("fontFamily"), 20) in _TABLE_FONTS else "system",
        "density": _bounded_text(value.get("density"), 20) if _bounded_text(value.get("density"), 20) in _TABLE_DENSITIES else "comfortable",
        "bandedRows": value.get("bandedRows") is not False,
        "emphasizeFirstColumn": value.get("emphasizeFirstColumn") is True,
    }


def normalize_chart_style(value: Any) -> dict[str, Any]:
    """Bound reusable chart presentation tokens without changing chart data or behavior."""
    if not isinstance(value, dict):
        return {}

    def bounded_number(raw: Any, fallback: float, minimum: float, maximum: float) -> float:
        try:
            number = float(raw)
        except (TypeError, ValueError):
            return fallback
        return max(minimum, min(maximum, number)) if math.isfinite(number) else fallback

    raw_palette = value.get("palette")
    palette = [_color(item, "") for item in raw_palette[:12]] if isinstance(raw_palette, list) else []
    palette = [item for item in palette if item]
    if len(palette) < 2:
        palette = list(_DEFAULT_CHART_STYLE["palette"])
    font = _bounded_text(value.get("fontFamily"), 20)
    height = _bounded_text(value.get("chartHeight"), 20)
    bar_width = _bounded_text(value.get("barWidth"), 20)
    return {
        "templateId": _bounded_text(value.get("templateId"), 120) or _DEFAULT_CHART_STYLE["templateId"],
        "backgroundColor": _color(value.get("backgroundColor"), _DEFAULT_CHART_STYLE["backgroundColor"]),
        "plotBackgroundColor": _color(value.get("plotBackgroundColor"), _DEFAULT_CHART_STYLE["plotBackgroundColor"]),
        "textColor": _color(value.get("textColor"), _DEFAULT_CHART_STYLE["textColor"]),
        "mutedTextColor": _color(value.get("mutedTextColor"), _DEFAULT_CHART_STYLE["mutedTextColor"]),
        "gridColor": _color(value.get("gridColor"), _DEFAULT_CHART_STYLE["gridColor"]),
        "axisColor": _color(value.get("axisColor"), _DEFAULT_CHART_STYLE["axisColor"]),
        "palette": palette,
        "fontFamily": font if font in _CHART_FONTS else _DEFAULT_CHART_STYLE["fontFamily"],
        "chartHeight": height if height in _CHART_HEIGHTS else _DEFAULT_CHART_STYLE["chartHeight"],
        "lineWidth": bounded_number(value.get("lineWidth"), 2.0, 1.0, 4.0),
        "pointRadius": bounded_number(value.get("pointRadius"), 2.5, 0.0, 6.0),
        "barRadius": bounded_number(value.get("barRadius"), 4.0, 0.0, 12.0),
        "barWidth": bar_width if bar_width in _CHART_BAR_WIDTHS else _DEFAULT_CHART_STYLE["barWidth"],
        "areaOpacity": bounded_number(value.get("areaOpacity"), 0.1, 0.0, 0.4),
    }


def normalize_table_metric_formats(value: Any, metric_fields: list[str]) -> list[dict[str, Any]]:
    """Normalize display-only metric percentage and precision settings."""
    if not isinstance(value, dict):
        return []
    metrics = set(metric_fields)
    seen: set[str] = set()
    formats: list[dict[str, Any]] = []
    raw_formats = value.get("metricFormats")
    for raw in raw_formats[:100] if isinstance(raw_formats, list) else []:
        if not isinstance(raw, dict):
            continue
        metric = _bounded_text(raw.get("metricField"), 300)
        if metric not in metrics or metric in seen:
            continue
        seen.add(metric)
        percent = raw.get("percent") is True
        decimal_places = None
        if raw.get("decimalPlaces") is not None and raw.get("decimalPlaces") != "":
            try:
                decimal_places = max(0, min(8, int(raw.get("decimalPlaces"))))
            except (TypeError, ValueError):
                decimal_places = None
        if not percent and decimal_places is None:
            continue
        formats.append({
            "metricField": metric,
            "percent": percent,
            **({"decimalPlaces": decimal_places} if decimal_places is not None else {}),
        })
    return formats


def normalize_table_metric_enhancements(
    value: dict[str, Any],
    metric_fields: list[str],
    dimension_fields: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize additive table/pivot ranking, progress and calculated-column configuration."""
    metrics = set(metric_fields)
    dimensions = set(dimension_fields)
    target_fields = metrics | dimensions

    rankings: list[dict[str, Any]] = []
    ranked_metrics: set[str] = set()
    raw_rankings = value.get("metricRankings")
    for raw in raw_rankings[:100] if isinstance(raw_rankings, list) else []:
        if not isinstance(raw, dict):
            continue
        metric = _bounded_text(raw.get("metricField"), 300)
        direction = _bounded_text(raw.get("direction"), 10)
        if metric not in metrics or metric in ranked_metrics:
            continue
        ranked_metrics.add(metric)
        rankings.append({"metricField": metric, "direction": direction if direction in _RANK_DIRECTIONS else "desc"})

    progress: list[dict[str, Any]] = []
    progress_metrics: set[str] = set()
    raw_progress = value.get("metricProgress")
    for progress_index, raw in enumerate(raw_progress[:100] if isinstance(raw_progress, list) else []):
        if not isinstance(raw, dict):
            continue
        metric = _bounded_text(raw.get("metricField"), 300)
        if metric not in metrics or metric in progress_metrics:
            continue
        denominator_mode = _bounded_text(raw.get("denominatorMode"), 20)
        if denominator_mode not in _PROGRESS_DENOMINATOR_MODES:
            denominator_mode = "selected_row"

        denominator_rules: list[dict[str, Any]] = []
        used_dimensions: set[str] = set()
        raw_denominator = raw.get("denominatorRules")
        for rule_index, raw_rule in enumerate(raw_denominator[:50] if isinstance(raw_denominator, list) else []):
            if not isinstance(raw_rule, dict):
                continue
            field = _bounded_text(raw_rule.get("field"), 300)
            values = _single_value_list(raw_rule.get("values"))
            if field not in dimensions or field in used_dimensions or not values:
                continue
            used_dimensions.add(field)
            denominator_rules.append({
                "id": _bounded_text(raw_rule.get("id"), 160) or f"progress-denominator-{progress_index}-{rule_index}",
                "field": field,
                "operator": "in",
                "values": values,
            })
        if denominator_mode == "selected_row" and not denominator_rules:
            continue

        association_rules: list[dict[str, Any]] = []
        raw_associations = raw.get("associationRules")
        for rule_index, raw_rule in enumerate(raw_associations[:50] if isinstance(raw_associations, list) else []):
            if not isinstance(raw_rule, dict):
                continue
            target_field = _bounded_text(raw_rule.get("targetField"), 300)
            source = _bounded_text(raw_rule.get("source"), 20)
            operator = _bounded_text(raw_rule.get("operator"), 10)
            style = _bounded_text(raw_rule.get("style"), 20)
            try:
                threshold = float(raw_rule.get("threshold"))
            except (TypeError, ValueError):
                continue
            if (
                target_field not in target_fields
                or source not in _ASSOCIATION_SOURCES
                or operator not in _ASSOCIATION_OPERATORS
                or style not in _ASSOCIATION_STYLES
                or not math.isfinite(threshold)
            ):
                continue
            association_rules.append({
                "id": _bounded_text(raw_rule.get("id"), 160) or f"progress-association-{progress_index}-{rule_index}",
                "source": source,
                "operator": operator,
                "threshold": threshold,
                "targetField": target_field,
                "style": style,
                "color": _color(raw_rule.get("color"), "#FFE6D5"),
                "replacementValue": _bounded_text(raw_rule.get("replacementValue"), 120),
            })

        progress_metrics.add(metric)
        progress.append({
            "metricField": metric,
            "denominatorMode": denominator_mode,
            "denominatorRules": denominator_rules,
            "color": _color(raw.get("color"), "#2CA66F"),
            "colorEnd": _color(raw.get("colorEnd"), _color(raw.get("color"), "#2CA66F")),
            "colorMode": (
                "solid"
                if _bounded_text(raw.get("colorMode"), 20) == "solid"
                else "reverse_gradient"
                if _bounded_text(raw.get("colorMode"), 20) == "reverse_gradient"
                else "gradient"
            ),
            "associationRules": association_rules,
        })

    calculated_columns: list[dict[str, Any]] = []
    calculated_ids: set[str] = set()
    raw_calculated = value.get("calculatedColumns")
    for index, raw in enumerate(raw_calculated[:20] if isinstance(raw_calculated, list) else []):
        if not isinstance(raw, dict):
            continue
        column_id = _bounded_text(raw.get("id"), 160)
        if not column_id or column_id in calculated_ids:
            continue
        calculated_ids.add(column_id)
        name = _bounded_text(raw.get("name"), 80) or f"新增列{index + 1}"
        expression = _bounded_text(raw.get("expression"), 2000)
        try:
            position = int(raw.get("position"))
        except (TypeError, ValueError):
            position = index
        calculated_columns.append({
            "id": column_id,
            "name": name,
            "position": max(0, min(200, position)),
            "expression": expression,
        })

    return rankings, progress, calculated_columns
