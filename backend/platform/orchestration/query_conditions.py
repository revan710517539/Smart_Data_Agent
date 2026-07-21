from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any


@dataclass(frozen=True)
class QueryConditions:
    filters: dict[str, Any] = field(default_factory=dict)
    time_range: dict[str, str] | None = None
    limit: int = 20
    sort_direction: str = "desc"


def parse_query_conditions(question: str, reference_date: date | None = None) -> QueryConditions:
    """Compile common Chinese time and Top-N language into typed conditions."""

    text = str(question or "").strip()
    today = reference_date or date.today()
    start, end, label = _parse_time_range(text, today)
    limit = _parse_limit(text)
    direction = "asc" if re.search(r"升序|最低|最少|尾部|bottom", text, re.IGNORECASE) else "desc"
    time_range = None
    filters: dict[str, Any] = {}
    if start and end:
        time_range = {
            "field": "month",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "label": label,
        }
        filters["month"] = {"gte": start.strftime("%Y-%m"), "lte": end.strftime("%Y-%m")}
    return QueryConditions(filters=filters, time_range=time_range, limit=limit, sort_direction=direction)


def _parse_limit(text: str) -> int:
    matches = (
        re.search(r"(?:top|TOP)\s*[-_ ]?(\d{1,3})", text),
        re.search(r"前\s*(\d{1,3})", text),
    )
    for match in matches:
        if match:
            return max(1, min(int(match.group(1)), 500))
    return 20


def _parse_time_range(text: str, today: date) -> tuple[date | None, date | None, str]:
    explicit = re.search(r"(20\d{2})\s*[年/-]\s*(1[0-2]|0?[1-9])\s*月?", text)
    if explicit:
        year, month = int(explicit.group(1)), int(explicit.group(2))
        return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]), "指定月份"
    recent = re.search(r"近\s*(\d{1,3})\s*天", text)
    if recent:
        days = max(1, min(int(recent.group(1)), 366))
        return today - timedelta(days=days - 1), today, f"近{days}天"
    if "上周" in text:
        current_monday = today - timedelta(days=today.weekday())
        return current_monday - timedelta(days=7), current_monday - timedelta(days=1), "上周"
    if "本周" in text or "这周" in text:
        return today - timedelta(days=today.weekday()), today, "本周"
    if "上月" in text:
        previous_end = today.replace(day=1) - timedelta(days=1)
        return previous_end.replace(day=1), previous_end, "上月"
    if "本月" in text or "这个月" in text:
        return today.replace(day=1), today, "本月"
    return None, None, ""
