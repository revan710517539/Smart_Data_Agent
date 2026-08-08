"""Deterministic metric snapshots for scheduled personal subscriptions."""

from __future__ import annotations

from html.parser import HTMLParser
from datetime import date
from math import isfinite
import re
from typing import Any

from backend.platform.semantic import SemanticQueryRequest


SMART_DATA_AGENT_SUBSCRIPTIONS_URL = "https://xujingbo-smart-data-agent.qifudigitech.com/notifications/subscriptions"


def collect_metric_snapshot(services: Any, tenant_id: str, user_id: str, metric: dict[str, Any]) -> dict[str, Any]:
    if str(metric.get("metricId") or metric.get("metric_id") or "").strip() in {"SYS_TEAMS_TEST_AMOUNT", "SYS_TEAMS_TEST_CUSTOMERS"}:
        return _test_metric_snapshot(metric)
    metric_code = _required(metric.get("metricCode") or metric.get("metric_code"), "metric_subscription_metric_code_required")
    dataset_id = _required(metric.get("datasetId") or metric.get("dataset_id"), "metric_subscription_dataset_required")
    time_dimension = str(metric.get("timeDimension") or metric.get("time_dimension") or "stat_date").strip()
    metric_name = str(metric.get("metricName") or metric.get("metric_name") or metric_code).strip()
    result = services.semantic_service.query(
        SemanticQueryRequest(
            question=f"获取{metric_name}最近两个统计周期，用于每日指标订阅",
            tenant_id=tenant_id,
            user_id=user_id,
            dataset_id=dataset_id,
            metrics=(metric_code,),
            dimensions=(time_dimension,),
            limit=2,
            sort_direction="desc",
            context={"surface": "metric_subscription", "purpose": "daily_snapshot"},
        )
    )
    points = []
    for row in result.data:
        value = _number(row.get(metric_code, row.get("metric_value")))
        if value is not None:
            points.append({"period": str(row.get(time_dimension) or ""), "value": value})
    if not points:
        raise ValueError("metric_subscription_no_data")
    points.sort(key=lambda item: item["period"])
    current = points[-1]
    previous = points[-2] if len(points) > 1 else None
    delta = current["value"] - previous["value"] if previous else None
    return {
        "summary": f"{metric_name}：{_display_number(current['value'])}{str(metric.get('unit') or '').strip()}",
        "metric_id": str(metric.get("metricId") or metric.get("metric_id") or ""),
        "metric_name": metric_name,
        "metric_code": metric_code,
        "period": current["period"],
        "value": current["value"],
        "unit": str(metric.get("unit") or "").strip(),
        "previous_value": previous["value"] if previous else None,
        "delta": delta,
        "source_dataset_id": dataset_id,
        "time_dimension": time_dimension,
    }


def _test_metric_snapshot(metric: dict[str, Any]) -> dict[str, Any]:
    """Stable, clearly identified values for an explicit Teams send test only."""
    metric_id = str(metric.get("metricId") or metric.get("metric_id") or "").strip()
    metric_name = str(metric.get("metricName") or metric.get("metric_name") or "测试指标").strip()
    current_value, previous_value = (128.6, 116.2) if metric_id == "SYS_TEAMS_TEST_AMOUNT" else (268, 241)
    return {
        "summary": f"{metric_name}：{_display_number(current_value)}{str(metric.get('unit') or '').strip()}",
        "metric_id": metric_id,
        "metric_name": metric_name,
        "metric_code": str(metric.get("metricCode") or metric.get("metric_code") or ""),
        "period": f"测试发送 {date.today().isoformat()}",
        "value": current_value,
        "unit": str(metric.get("unit") or "").strip(),
        "previous_value": previous_value,
        "delta": current_value - previous_value,
        "source_dataset_id": "sda_teams_test",
        "time_dimension": "test_send_time",
        "is_test_metric": True,
    }


def normalize_teams_message_template(value: Any, metric_ids: list[str]) -> dict[str, Any]:
    """Return a bounded, deterministic Teams Markdown template.

    The 360Teams self-message API accepts Markdown rather than arbitrary HTML.
    Template formatting is therefore intentionally constrained to text hierarchy
    and a color marker instead of passing untrusted markup through to Teams.
    """
    raw = value if isinstance(value, dict) else {}
    accepted_ids = {str(metric_id).strip() for metric_id in metric_ids if str(metric_id).strip()}
    title = _template_text(raw.get("title"), "每日经营快报", 50)
    subtitle = _template_text(raw.get("subtitle"), "当前机构 · T+1", 120)
    footer = _template_text(raw.get("footer"), "只发送已授权数据，不展示 JSON。", 240)
    body = _template_body(raw.get("bodyHtml") or raw.get("body_html"), accepted_ids)
    raw_metrics = raw.get("metrics") if isinstance(raw.get("metrics"), list) else []
    seen: set[str] = set()
    metrics: list[dict[str, str]] = []
    for item in raw_metrics:
        if not isinstance(item, dict):
            continue
        metric_id = str(item.get("metricId") or item.get("metric_id") or "").strip()
        if metric_id not in accepted_ids or metric_id in seen:
            continue
        seen.add(metric_id)
        metrics.append(
            {
                "metricId": metric_id,
                "fontSize": _choice(item.get("fontSize"), {"small", "normal", "large"}, "normal"),
                "color": _choice(item.get("color"), {"slate", "blue", "green", "amber", "red"}, "slate"),
            }
        )
    for metric_id in metric_ids:
        normalized_id = str(metric_id).strip()
        if normalized_id and normalized_id not in seen:
            metrics.append({"metricId": normalized_id, "fontSize": "normal", "color": "slate"})
    return {"title": title, "subtitle": subtitle, "footer": footer, "metrics": metrics, "body": body}


def render_teams_metric_markdown(payload: dict[str, Any]) -> tuple[str, str]:
    """Render legacy one-metric and template-backed multi-metric snapshots."""
    template_backed = isinstance(payload.get("snapshots"), list) or isinstance(payload.get("message_template"), dict)
    snapshots = payload.get("snapshots") if isinstance(payload.get("snapshots"), list) else [payload]
    normalized_snapshots = [dict(item) for item in snapshots if isinstance(item, dict) and item.get("metric_name")]
    if not normalized_snapshots:
        raise ValueError("metric_subscription_no_snapshots")
    snapshot_by_id = {str(item.get("metric_id") or "").strip(): item for item in normalized_snapshots}
    fallback_ids = [str(item.get("metric_id") or "").strip() for item in normalized_snapshots]
    template = normalize_teams_message_template(payload.get("message_template"), fallback_ids)
    title = template["title"] if template_backed else f"每日指标 · {normalized_snapshots[0]['metric_name']}"
    if template.get("body"):
        rendered_body = _render_template_body(str(template["body"]), snapshot_by_id)
        return title[:50], rendered_body[:5000]
    lines = [f"# {title}", template["subtitle"], "---", "**核心指标**"]
    for item in template["metrics"]:
        snapshot = snapshot_by_id.get(item["metricId"])
        if snapshot is None:
            continue
        unit = str(snapshot.get("unit") or "")
        name = str(snapshot.get("metric_name") or "指标")
        value = f"{_display_number(snapshot['value'])}{unit}"
        marker = {"slate": "⚪", "blue": "🔵", "green": "🟢", "amber": "🟠", "red": "🔴"}[item["color"]]
        heading = {"small": "", "normal": "**", "large": "## **"}[item["fontSize"]]
        closing = "**" if item["fontSize"] in {"normal", "large"} else ""
        if item["fontSize"] == "large":
            line = f"{heading}{marker} {name}：{value}{closing}"
        else:
            line = f"{marker} {heading}{name}：{value}{closing}"
        lines.append(line)
        lines.append(f"统计周期：{snapshot.get('period') or '最新可用周期'}")
        if snapshot.get("previous_value") is not None:
            delta = float(snapshot.get("delta") or 0)
            sign = "+" if delta > 0 else ""
            lines.append(f"较上一期：{sign}{_display_number(delta)}{unit}")
    lines.extend(["---", template["footer"], "来源：Smart Data Agent 已授权指标查询"])
    return title[:50], "\n\n".join(lines)[:5000]


def _required(value: Any, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(code)
    return text


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _display_number(value: Any) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.4f}".rstrip("0").rstrip(".")


def _template_text(value: Any, fallback: str, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    return (text or fallback)[:maximum]


def _choice(value: Any, allowed: set[str], fallback: str) -> str:
    choice = str(value or "").strip().lower()
    return choice if choice in allowed else fallback


class _TemplateBodyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._link_targets: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in {"br", "p", "div", "h1", "h2", "h3", "li", "hr"}:
            self.parts.append("\n")
        if normalized_tag in {"h1", "h2", "h3"}:
            self.parts.append({"h1": "# ", "h2": "## ", "h3": "### "}[normalized_tag])
        attribute_map = {str(key).lower(): str(value or "") for key, value in attrs}
        style = attribute_map.get("style", "").lower()
        color = attribute_map.get("color", "").lower()
        color_match = re.search(r"color\s*:\s*(#[0-9a-f]{3,8}|rgb\([^)]*\))", style)
        normalized_color = color_match.group(1) if color_match else color
        marker = _color_marker(normalized_color)
        if marker:
            self.parts.append(marker + " ")
        size_match = re.search(r"font-size\s*:\s*(\d+)px", style)
        if normalized_tag == "font" and attribute_map.get("size") in {"5", "6", "7"}:
            self.parts.append("## ")
        elif size_match and int(size_match.group(1)) >= 18:
            self.parts.append("## ")
        if normalized_tag == "a":
            href = attribute_map.get("href", "")
            if href == SMART_DATA_AGENT_SUBSCRIPTIONS_URL:
                self.parts.append("[")
                self._link_targets.append(href)
            else:
                self._link_targets.append(None)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a":
            href = self._link_targets.pop() if self._link_targets else None
            if href:
                self.parts.append(f"]({href})")
        if tag.lower() in {"p", "div", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _template_body(value: Any, accepted_ids: set[str]) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parser = _TemplateBodyParser()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        return ""
    text = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
    text = text[:4000]
    allowed = "|".join(re.escape(metric_id) for metric_id in sorted(accepted_ids, key=len, reverse=True))
    if allowed:
        text = re.sub(r"\{\{metric:(" + allowed + r")\}\}", r"{{metric:\1}}", text)
        text = re.sub(r"\{\{metric:(?!" + allowed + r"\}\})[^}]+\}\}", "", text)
    else:
        text = re.sub(r"\{\{metric:[^}]+\}\}", "", text)
    return text


def _render_template_body(body: str, snapshots: dict[str, dict[str, Any]]) -> str:
    def replace(match: re.Match[str]) -> str:
        snapshot = snapshots.get(match.group(1))
        if snapshot is None:
            return ""
        unit = str(snapshot.get("unit") or "")
        value = f"{_display_number(snapshot['value'])}{unit}"
        lines = [f"**{snapshot.get('metric_name') or '指标'}：{value}**", f"统计周期：{snapshot.get('period') or '最新可用周期'}"]
        if snapshot.get("previous_value") is not None:
            delta = float(snapshot.get("delta") or 0)
            lines.append(f"较上一期：{'+' if delta > 0 else ''}{_display_number(delta)}{unit}")
        return "\n".join(lines)

    rendered = re.sub(r"\{\{metric:([^}]+)\}\}", replace, body)
    return rendered + "\n\n来源：Smart Data Agent 已授权指标查询"


def _color_marker(value: str) -> str:
    color = str(value or "").lower().replace(" ", "")
    if color in {"#007aff", "rgb(0,122,255)"}:
        return "🔵"
    if color in {"#248a3d", "rgb(36,138,61)"}:
        return "🟢"
    if color in {"#b26a00", "rgb(178,106,0)"}:
        return "🟠"
    if color in {"#d70015", "rgb(215,0,21)"}:
        return "🔴"
    return ""
