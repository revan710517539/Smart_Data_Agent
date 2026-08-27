from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from backend.platform.database.identity import PostgreSQLIdentityResolver


_SECRET_PARTS = ("password", "secret", "token", "authorization", "cookie", "credential", "sql", "rows", "raw_data")
_TEXT_KEYS = {"question", "reply", "input", "answer"}


def sanitize_interaction_extension(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if depth > 3:
        return "[depth_limited]"
    normalized_key = key.lower().replace("-", "_")
    if any(part in normalized_key for part in _SECRET_PARTS):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(item_key)[:80]: sanitize_interaction_extension(item_value, key=str(item_key), depth=depth + 1) for item_key, item_value in list(value.items())[:30]}
    if isinstance(value, list):
        return [sanitize_interaction_extension(item, key=key, depth=depth + 1) for item in value[:20]]
    if isinstance(value, str):
        text = re.sub(r"(?i)(password|token|secret|authorization|cookie)\s*[:=]\s*\S+", r"\1=[redacted]", value)
        return text[:500] if normalized_key in _TEXT_KEYS else text[:240]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:240]


def normalize_interaction_event(
    *,
    tenant_id: str,
    actor_user_id: str,
    actor_account: str,
    event_name: str,
    event_type: str,
    page_path: str = "",
    page_name: str = "",
    chart_id: str = "",
    chart_name: str = "",
    resource_type: str = "",
    resource_id: str = "",
    extension: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_type = event_type.strip().lower()
    if normalized_type not in {"click", "view"}:
        raise ValueError("interaction_event_type_invalid")
    normalized_name = event_name.strip()
    if not normalized_name or len(normalized_name) > 120:
        raise ValueError("interaction_event_name_invalid")
    return {
        "event_id": str(uuid4()),
        "tenant_id": tenant_id,
        "actor_user_id": actor_user_id,
        "actor_account": actor_account.strip()[:320],
        "event_name": normalized_name,
        "event_type": normalized_type,
        "page_path": page_path.strip()[:500],
        "page_name": page_name.strip()[:200],
        "chart_id": chart_id.strip()[:200],
        "chart_name": chart_name.strip()[:300],
        "resource_type": resource_type.strip()[:120],
        "resource_id": resource_id.strip()[:200],
        "extension": sanitize_interaction_extension(extension or {}),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }


class InMemoryInteractionEventStore:
    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []
        self._lock = RLock()

    def write(self, **values: Any) -> dict[str, Any]:
        event = normalize_interaction_event(**values)
        with self._lock:
            self._items.append(event)
        return dict(event)

    def list(self, tenant_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in reversed(self._items) if item["tenant_id"] == tenant_id][:_bounded_limit(limit)]

    def list_range(
        self,
        tenant_id: str,
        *,
        since: str,
        until: str,
        limit: int = 20_000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        start = _parse_datetime(since)
        end = _parse_datetime(until)
        bounded_offset = max(0, int(offset or 0))
        bounded_limit = _bounded_analytics_limit(limit)
        with self._lock:
            matches = [
                dict(item)
                for item in reversed(self._items)
                if item["tenant_id"] == tenant_id and start <= _parse_datetime(item["occurred_at"]) < end
            ]
        return matches[bounded_offset: bounded_offset + bounded_limit]

    def count_range(self, tenant_id: str, *, since: str, until: str) -> int:
        start = _parse_datetime(since)
        end = _parse_datetime(until)
        with self._lock:
            return sum(
                1
                for item in self._items
                if item["tenant_id"] == tenant_id and start <= _parse_datetime(item["occurred_at"]) < end
            )

    def list_global_range(self, *, since: str, until: str, limit: int = 20_000, offset: int = 0) -> list[dict[str, Any]]:
        start = _parse_datetime(since)
        end = _parse_datetime(until)
        bounded_offset = max(0, int(offset or 0))
        bounded_limit = _bounded_analytics_limit(limit)
        with self._lock:
            matches = [
                dict(item)
                for item in reversed(self._items)
                if start <= _parse_datetime(item["occurred_at"]) < end
            ]
        return matches[bounded_offset: bounded_offset + bounded_limit]

    def count_global_range(self, *, since: str, until: str) -> int:
        start = _parse_datetime(since)
        end = _parse_datetime(until)
        with self._lock:
            return sum(1 for item in self._items if start <= _parse_datetime(item["occurred_at"]) < end)


class MySQLInteractionEventStore:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    def write(self, **values: Any) -> dict[str, Any]:
        event = normalize_interaction_event(**values)
        occurred_at = _mysql_datetime(event["occurred_at"])
        with self.pool.transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, event["tenant_id"])
            actor_key = PostgreSQLIdentityResolver.user_id(connection, event["actor_user_id"], required=False)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_user_interaction_events(
                      interaction_event_id, tenant_id, actor_user_id, actor_account,
                      event_name, event_type, page_path, page_name, chart_id, chart_name,
                      resource_type, resource_id, extension, occurred_at, created_by
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        event["event_id"], tenant_key, actor_key, event["actor_account"],
                        event["event_name"], event["event_type"], event["page_path"], event["page_name"],
                        event["chart_id"] or None, event["chart_name"] or None,
                        event["resource_type"] or None, event["resource_id"] or None,
                        json.dumps(event["extension"], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                        occurred_at, actor_key,
                    ),
                )
        return event

    def list_range(
        self,
        tenant_id: str,
        *,
        since: str,
        until: str,
        limit: int = 20_000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        bounded_limit = _bounded_analytics_limit(limit)
        bounded_offset = max(0, min(int(offset or 0), 100_000))
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT e.interaction_event_id, tenant.tenant_code,
                           COALESCE(actor.external_subject, e.actor_account, 'unknown') AS actor_user_code,
                           COALESCE(NULLIF(TRIM(actor.display_name), ''), e.actor_account, '未知用户') AS actor_name,
                           COALESCE(e.actor_account, '') AS actor_account,
                           e.event_name, e.event_type, e.page_path, e.page_name,
                           COALESCE(e.chart_id, ''), COALESCE(e.chart_name, ''),
                           COALESCE(e.resource_type, ''), COALESCE(e.resource_id, ''),
                           e.extension, e.occurred_at
                    FROM platform_user_interaction_events e
                    JOIN platform_tenants tenant ON tenant.tenant_id=e.tenant_id
                    LEFT JOIN platform_user_profiles actor ON actor.user_id=e.actor_user_id
                    WHERE e.tenant_id=%s AND e.occurred_at >= %s AND e.occurred_at < %s
                    ORDER BY e.occurred_at DESC, e.interaction_event_id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (tenant_key, since, until, bounded_limit, bounded_offset),
                )
                rows = list(cursor.fetchall())
        return [_interaction_row(row) for row in rows]

    def count_range(self, tenant_id: str, *, since: str, until: str) -> int:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM platform_user_interaction_events
                    WHERE tenant_id=%s AND occurred_at >= %s AND occurred_at < %s
                    """,
                    (tenant_key, since, until),
                )
                row = cursor.fetchone()
        return int(_row_value(row, "total", 0) or 0)

    def list_global_range(
        self,
        *,
        since: str,
        until: str,
        limit: int = 20_000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        bounded_limit = _bounded_analytics_limit(limit)
        bounded_offset = max(0, min(int(offset or 0), 100_000))
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT e.interaction_event_id, tenant.tenant_code,
                       COALESCE(actor.external_subject, e.actor_account, 'unknown') AS actor_user_code,
                       COALESCE(NULLIF(TRIM(actor.display_name), ''), e.actor_account, '未知用户') AS actor_name,
                       COALESCE(e.actor_account, '') AS actor_account,
                       e.event_name, e.event_type, e.page_path, e.page_name,
                       COALESCE(e.chart_id, ''), COALESCE(e.chart_name, ''),
                       COALESCE(e.resource_type, ''), COALESCE(e.resource_id, ''),
                       e.extension, e.occurred_at
                FROM platform_user_interaction_events e
                JOIN platform_tenants tenant ON tenant.tenant_id=e.tenant_id
                LEFT JOIN platform_user_profiles actor ON actor.user_id=e.actor_user_id
                WHERE e.occurred_at >= %s AND e.occurred_at < %s
                ORDER BY e.occurred_at DESC, e.interaction_event_id DESC
                LIMIT %s OFFSET %s
                """,
                (since, until, bounded_limit, bounded_offset),
            )
            rows = list(cursor.fetchall())
        return [_interaction_row(row) for row in rows]

    def count_global_range(self, *, since: str, until: str) -> int:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM platform_user_interaction_events
                WHERE occurred_at >= %s AND occurred_at < %s
                """,
                (since, until),
            )
            row = cursor.fetchone()
        return int(_row_value(row, "total", 0) or 0)


def build_interaction_analytics(
    events: list[dict[str, Any]],
    *,
    since: str,
    until: str,
    total_count: int | None = None,
    timeline_actor_user_id: str = "",
    timeline_page: int = 1,
    timeline_page_size: int = 50,
    timezone_name: str = "Asia/Shanghai",
    session_gap_minutes: int = 30,
) -> dict[str, Any]:
    """Build a bounded interaction snapshot without a second analytics store."""

    zone = ZoneInfo(timezone_name)
    start = _parse_datetime(since)
    end = _parse_datetime(until)
    ordered = sorted(
        (
            {**event, "_occurred": _parse_datetime(event.get("occurred_at"))}
            for event in events
            if start <= _parse_datetime(event.get("occurred_at")) < end
        ),
        key=lambda event: (event["_occurred"], str(event.get("event_id") or "")),
    )
    by_actor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in ordered:
        by_actor[_actor_key(event)].append(event)

    session_gap = timedelta(minutes=session_gap_minutes)
    session_starts: list[tuple[str, datetime]] = []
    user_summaries: list[dict[str, Any]] = []
    for actor_key, actor_events in by_actor.items():
        visits = 0
        previous: datetime | None = None
        pages: Counter[str] = Counter()
        for event in actor_events:
            occurred = event["_occurred"]
            if previous is None or occurred - previous > session_gap:
                visits += 1
                session_starts.append((actor_key, occurred))
            previous = occurred
            page = str(event.get("page_name") or event.get("page_path") or "").strip()
            if page:
                pages[page] += 1
        last_event = actor_events[-1]
        user_summaries.append({
            "actor_user_id": str(last_event.get("actor_user_id") or actor_key),
            "actor_name": str(last_event.get("actor_name") or last_event.get("actor_account") or "未知用户"),
            "actor_account": str(last_event.get("actor_account") or ""),
            "visits": visits,
            "events": len(actor_events),
            "last_seen": last_event["_occurred"].isoformat(),
            "top_page": pages.most_common(1)[0][0] if pages else "",
            "tenant_ids": sorted({str(event.get("tenant_id") or "") for event in actor_events if str(event.get("tenant_id") or "")}),
        })
    user_summaries.sort(key=lambda item: (-int(item["visits"]), -int(item["events"]), str(item["actor_name"])))

    weekly: dict[str, dict[str, Any]] = {}
    for actor_key, occurred in session_starts:
        local = occurred.astimezone(zone)
        week_start = (local.date() - timedelta(days=local.weekday())).isoformat()
        bucket = weekly.setdefault(week_start, {"week_start": week_start, "visits": 0, "events": 0, "actors": set(), "hours": Counter()})
        bucket["visits"] += 1
        bucket["actors"].add(actor_key)
    for event in ordered:
        local = event["_occurred"].astimezone(zone)
        week_start = (local.date() - timedelta(days=local.weekday())).isoformat()
        bucket = weekly.setdefault(week_start, {"week_start": week_start, "visits": 0, "events": 0, "actors": set(), "hours": Counter()})
        bucket["events"] += 1
        bucket["actors"].add(_actor_key(event))
        bucket["hours"][local.hour] += 1
    weekly_items = [
        {
            "week_start": key,
            "visitors": len(bucket["actors"]),
            "visits": bucket["visits"],
            "events": bucket["events"],
            "peak_hour": max(bucket["hours"], key=lambda hour: (bucket["hours"][hour], -hour), default=None),
        }
        for key, bucket in sorted(weekly.items())
    ]

    hour_counts: Counter[int] = Counter(event["_occurred"].astimezone(zone).hour for event in ordered)
    hourly = [{"hour": hour, "events": hour_counts[hour]} for hour in range(24)]
    page_counts: Counter[str] = Counter(
        str(event.get("page_name") or event.get("page_path") or "未知页面").strip() or "未知页面"
        for event in ordered
        if str(event.get("event_name") or "") == "page_view"
    )
    metric_counts = _extension_value_counts(ordered, "metric")
    dimension_counts = _extension_value_counts(ordered, "dimension")
    style_counts = _extension_value_counts(ordered, "style")
    breakpoints = _detect_breakpoints(by_actor, session_gap_minutes=session_gap_minutes)
    breakpoint_counts = Counter(item["type"] for item in breakpoints)
    breakpoints_by_actor = Counter(item["actor_user_id"] for item in breakpoints)
    for summary in user_summaries:
        summary["breakpoints"] = breakpoints_by_actor[str(summary["actor_user_id"])]

    local_now = end.astimezone(zone)
    this_week_start = (local_now.date() - timedelta(days=local_now.weekday())).isoformat()
    this_week_visits = next((item["visits"] for item in weekly_items if item["week_start"] == this_week_start), 0)
    peak_hour = hour_counts.most_common(1)[0][0] if hour_counts else None
    timeline_source = list(reversed(ordered))
    actor_filter = timeline_actor_user_id.strip()
    if actor_filter:
        timeline_source = [event for event in timeline_source if str(event.get("actor_user_id") or "") == actor_filter]
    page = max(1, int(timeline_page or 1))
    page_size = max(1, min(int(timeline_page_size or 50), 100))
    offset = (page - 1) * page_size
    timeline_items = [_public_event(event) for event in timeline_source[offset: offset + page_size]]
    counted = len(ordered) if total_count is None else max(0, int(total_count))
    visits = len(session_starts)
    return {
        "range": {
            "since": start.isoformat(),
            "until": end.isoformat(),
            "timezone": timezone_name,
            "session_gap_minutes": session_gap_minutes,
        },
        "summary": {
            "total_visitors": len(by_actor),
            "total_visits": visits,
            "total_events": counted,
            "average_visits_per_user": round(visits / len(by_actor), 1) if by_actor else 0,
            "this_week_visits": this_week_visits,
            "active_days": len({event["_occurred"].astimezone(zone).date() for event in ordered}),
            "peak_hour": peak_hour,
        },
        "weekly": weekly_items,
        "hourly": hourly,
        "top_pages": _counter_items(page_counts),
        "top_metrics": _counter_items(metric_counts),
        "top_dimensions": _counter_items(dimension_counts),
        "top_styles": _counter_items(style_counts),
        "users": user_summaries[:100],
        "tenant_ids": sorted({str(event.get("tenant_id") or "") for event in ordered if str(event.get("tenant_id") or "")}),
        "breakpoint_summary": {
            "menu_without_page_view": breakpoint_counts["menu_without_page_view"],
            "configuration_not_completed": breakpoint_counts["configuration_not_completed"],
            "repeated_action": breakpoint_counts["repeated_action"],
            "total": len(breakpoints),
        },
        "breakpoints": breakpoints[:100],
        "timeline": {
            "items": timeline_items,
            "total": len(timeline_source),
            "page": page,
            "page_size": page_size,
        },
        "sampled_events": len(ordered),
        "truncated": counted > len(ordered),
    }


def _detect_breakpoints(by_actor: dict[str, list[dict[str, Any]]], *, session_gap_minutes: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    panel_actions = {
        "visual_metric_click": "metric",
        "visual_dimension_click": "dimension",
        "visual_style_click": "style",
        "visual_condition_click": "condition",
    }
    for actor_events in by_actor.values():
        for index, event in enumerate(actor_events):
            name = str(event.get("event_name") or "")
            occurred = event["_occurred"]
            following = [item for item in actor_events[index + 1:] if item["_occurred"] - occurred <= timedelta(minutes=2)]
            target_path = str((event.get("extension") or {}).get("target_path") or "").strip()
            if name in {"primary_menu_click", "secondary_menu_click"} and target_path and target_path != str(event.get("page_path") or "") and not any(
                str(item.get("event_name") or "") == "page_view" and item["_occurred"] - occurred <= timedelta(seconds=30)
                and str(item.get("page_path") or "") == target_path
                for item in following
            ):
                results.append(_breakpoint(event, "menu_without_page_view", "菜单点击后 30 秒内未发现页面曝光"))
            action = panel_actions.get(name)
            if action and not any(
                str(item.get("event_name") or "") == "visualization_result"
                and str((item.get("extension") or {}).get("action") or "") == action
                for item in following
            ):
                results.append(_breakpoint(event, "configuration_not_completed", f"打开{_action_label(action)}后 2 分钟内未记录最终选择"))
        for index in range(2, len(actor_events)):
            recent = actor_events[index - 2:index + 1]
            signature = [(str(item.get("event_name") or ""), str(item.get("resource_id") or item.get("page_path") or "")) for item in recent]
            if len(set(signature)) == 1 and recent[-1]["_occurred"] - recent[0]["_occurred"] <= timedelta(minutes=2):
                previous_signature = (
                    str(actor_events[index - 3].get("event_name") or ""),
                    str(actor_events[index - 3].get("resource_id") or actor_events[index - 3].get("page_path") or ""),
                ) if index >= 3 else None
                if previous_signature != signature[0]:
                    results.append(_breakpoint(recent[-1], "repeated_action", "2 分钟内连续 3 次执行同一操作"))
    results.sort(key=lambda item: item["occurred_at"], reverse=True)
    return results


def _breakpoint(event: dict[str, Any], kind: str, description: str) -> dict[str, Any]:
    return {
        "type": kind,
        "actor_user_id": str(event.get("actor_user_id") or _actor_key(event)),
        "actor_name": str(event.get("actor_name") or event.get("actor_account") or "未知用户"),
        "event_name": str(event.get("event_name") or ""),
        "page_path": str(event.get("page_path") or ""),
        "tenant_id": str(event.get("tenant_id") or ""),
        "occurred_at": event["_occurred"].isoformat(),
        "description": description,
    }


def _action_label(action: str) -> str:
    return {"metric": "指标", "dimension": "维度", "style": "样式", "condition": "条件"}.get(action, action)


def _extension_value_counts(events: list[dict[str, Any]], kind: str) -> Counter[str]:
    keys = {
        "metric": ("metric", "metric_code", "metric_field", "metric_fields", "metric_codes", "metrics", "selected_metrics"),
        "dimension": ("dimension", "dimension_code", "dimension_field", "dimension_fields", "dimension_codes", "dimensions", "selected_dimensions"),
        "style": ("style", "style_code", "chart_type", "visualization_type"),
    }[kind]
    counter: Counter[str] = Counter()
    for event in events:
        extension = event.get("extension") if isinstance(event.get("extension"), dict) else {}
        for key in keys:
            value = extension.get(key)
            values = value if isinstance(value, list) else [value]
            for item in values:
                text = str(item or "").strip()
                if text:
                    counter[text[:120]] += 1
    return counter


def _counter_items(counter: Counter[str], limit: int = 10) -> list[dict[str, Any]]:
    return [{"value": value, "count": count} for value, count in counter.most_common(limit)]


def _actor_key(event: dict[str, Any]) -> str:
    return str(event.get("actor_user_id") or event.get("actor_account") or "unknown")


def _public_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": str(event.get("event_id") or ""),
        "tenant_id": str(event.get("tenant_id") or ""),
        "actor_user_id": str(event.get("actor_user_id") or ""),
        "actor_name": str(event.get("actor_name") or event.get("actor_account") or "未知用户"),
        "actor_account": str(event.get("actor_account") or ""),
        "event_name": str(event.get("event_name") or ""),
        "event_type": str(event.get("event_type") or ""),
        "page_path": str(event.get("page_path") or ""),
        "page_name": str(event.get("page_name") or ""),
        "chart_id": str(event.get("chart_id") or ""),
        "chart_name": str(event.get("chart_name") or ""),
        "resource_type": str(event.get("resource_type") or ""),
        "resource_id": str(event.get("resource_id") or ""),
        "extension": event.get("extension") if isinstance(event.get("extension"), dict) else {},
        "occurred_at": event["_occurred"].isoformat(),
    }


def _interaction_row(row: Any) -> dict[str, Any]:
    occurred = _row_value(row, "occurred_at", 14)
    if isinstance(occurred, datetime):
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
        occurred_at = occurred.astimezone(timezone.utc).isoformat()
    else:
        occurred_at = _parse_datetime(occurred).isoformat()
    extension = _row_value(row, "extension", 13)
    if isinstance(extension, str):
        try:
            extension = json.loads(extension)
        except json.JSONDecodeError:
            extension = {}
    return {
        "event_id": str(_row_value(row, "interaction_event_id", 0)),
        "tenant_id": str(_row_value(row, "tenant_code", 1)),
        "actor_user_id": str(_row_value(row, "actor_user_code", 2)),
        "actor_name": str(_row_value(row, "actor_name", 3)),
        "actor_account": str(_row_value(row, "actor_account", 4)),
        "event_name": str(_row_value(row, "event_name", 5)),
        "event_type": str(_row_value(row, "event_type", 6)),
        "page_path": str(_row_value(row, "page_path", 7) or ""),
        "page_name": str(_row_value(row, "page_name", 8) or ""),
        "chart_id": str(_row_value(row, "chart_id", 9) or ""),
        "chart_name": str(_row_value(row, "chart_name", 10) or ""),
        "resource_type": str(_row_value(row, "resource_type", 11) or ""),
        "resource_id": str(_row_value(row, "resource_id", 12) or ""),
        "extension": extension if isinstance(extension, dict) else {},
        "occurred_at": occurred_at,
    }


def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[index]
    except (IndexError, KeyError, TypeError):
        return None


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _mysql_datetime(value: Any) -> datetime:
    """Return a UTC-naive value accepted by MySQL DATETIME columns."""
    return _parse_datetime(value).replace(tzinfo=None)


def _bounded_limit(value: int) -> int:
    return max(1, min(int(value or 100), 500))


def _bounded_analytics_limit(value: int) -> int:
    return max(1, min(int(value or 20_000), 20_000))
