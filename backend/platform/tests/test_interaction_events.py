from __future__ import annotations

import http.client
import json
import threading
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from backend.platform.api.router import API_ROUTE_REGISTRY
from backend.platform.api.routes.interaction_events import _bounded_days, _require_explicit_session, _require_interaction_analytics_admin
from backend.platform.api.server import create_server
from backend.platform.interaction_events import InMemoryInteractionEventStore, build_interaction_analytics, sanitize_interaction_extension
from backend.platform.security import AuthenticationError


def test_interaction_events_are_bounded_and_redact_sensitive_fields() -> None:
    store = InMemoryInteractionEventStore()
    event = store.write(
        tenant_id="tenant_test",
        actor_user_id="user_test",
        actor_account="operator@example.com",
        event_name="visual_follow_up_click",
        event_type="click",
        page_path="/weekly-report",
        page_name="经营周报",
        chart_id="chart_1",
        chart_name="贷款余额趋势",
        resource_type="visualization",
        resource_id="chart_1",
        extension={
            "question": "请分析趋势 password=should-not-leak " + "x" * 800,
            "sql": "select customer_name from raw_business_table",
            "rows": [{"customer": "sensitive"}],
        },
    )

    assert event["event_type"] == "click"
    assert event["chart_name"] == "贷款余额趋势"
    assert len(event["extension"]["question"]) <= 500
    assert "should-not-leak" not in event["extension"]["question"]
    assert event["extension"]["sql"] == "[redacted]"
    assert event["extension"]["rows"] == "[redacted]"


def test_interaction_event_contract_rejects_unknown_type() -> None:
    store = InMemoryInteractionEventStore()
    try:
        store.write(
            tenant_id="tenant_test",
            actor_user_id="user_test",
            actor_account="operator@example.com",
            event_name="bad",
            event_type="keypress",
        )
    except ValueError as exc:
        assert str(exc) == "interaction_event_type_invalid"
    else:  # pragma: no cover
        raise AssertionError("unknown event type must fail closed")


def test_interaction_event_route_and_mysql_migration_are_registered() -> None:
    assert API_ROUTE_REGISTRY.has_route("POST", "/api/interaction-events")
    assert API_ROUTE_REGISTRY.has_route("GET", "/api/interaction-events/analytics")


def test_interaction_event_route_requires_an_explicit_session() -> None:
    try:
        _require_explicit_session(SimpleNamespace(headers={}))
    except AuthenticationError as exc:
        assert str(exc) == "interaction_event_login_required"
    else:  # pragma: no cover
        raise AssertionError("anonymous telemetry writes must fail closed")

    _require_explicit_session(SimpleNamespace(headers={"Cookie": "sda_session=signed-session"}))


def test_interaction_analytics_requires_global_super_admin() -> None:
    context = SimpleNamespace(user_id="user_test", tenant_id="tenant_test")
    denied = SimpleNamespace(
        services=SimpleNamespace(permission_broker=SimpleNamespace(enforcer=SimpleNamespace(has_super_admin_role=lambda *_: False))),
    )
    try:
        _require_interaction_analytics_admin(denied, context)
    except PermissionError as exc:
        assert str(exc) == "global_super_admin_required"
    else:  # pragma: no cover
        raise AssertionError("non-admin interaction analytics access must fail closed")

    allowed = SimpleNamespace(
        services=SimpleNamespace(permission_broker=SimpleNamespace(enforcer=SimpleNamespace(has_super_admin_role=lambda *_: True))),
    )
    _require_interaction_analytics_admin(allowed, context)


def test_interaction_analytics_defaults_to_seven_days_and_bounds_explicit_values() -> None:
    assert _bounded_days(None) == 7
    assert _bounded_days("") == 7
    assert _bounded_days("1") == 1
    assert _bounded_days("365") == 90


def test_recursive_sanitizer_limits_depth_and_collection_size() -> None:
    value = sanitize_interaction_extension({"items": list(range(100)), "nested": {"a": {"b": {"c": {"d": "hidden"}}}}})
    assert len(value["items"]) == 20
    assert "depth_limited" in str(value["nested"])


def test_lightweight_analytics_derives_visits_usage_and_breakpoints_from_same_events() -> None:
    events = [
        _event("e1", "user_a", "login_submit", "2026-08-25T00:00:00+00:00", page_name="登录"),
        _event("e2", "user_a", "secondary_menu_click", "2026-08-25T00:00:10+00:00", page_name="智能分析", extension={"target_path": "/self-analysis/query"}),
        _event("e3", "user_a", "page_view", "2026-08-25T00:00:11+00:00", page_name="智能分析"),
        _event("e4", "user_a", "visual_metric_click", "2026-08-25T00:01:00+00:00", chart_name="贷款趋势"),
        _event(
            "e5", "user_a", "visualization_result", "2026-08-25T00:01:10+00:00", chart_name="贷款趋势",
            extension={"action": "metric", "metric_fields": ["贷款余额"]},
        ),
        _event(
            "e6", "user_a", "visualization_result", "2026-08-25T00:31:11+00:00", chart_name="贷款趋势",
            extension={"action": "dimension", "dimension_fields": ["机构"], "chart_type": "line"},
        ),
        _event("e7", "user_b", "secondary_menu_click", "2026-08-25T01:00:00+00:00", page_name="经营周报", extension={"target_path": "/weekly-report"}),
    ]

    result = build_interaction_analytics(
        events,
        since="2026-08-24T00:00:00+00:00",
        until="2026-08-26T00:00:00+00:00",
        total_count=len(events),
    )

    assert result["summary"]["total_visitors"] == 2
    assert result["summary"]["total_visits"] == 3
    assert result["summary"]["total_events"] == 7
    assert result["weekly"][0]["peak_hour"] == 8
    assert result["top_metrics"][0] == {"value": "贷款余额", "count": 1}
    assert result["top_dimensions"][0] == {"value": "机构", "count": 1}
    assert result["top_styles"][0] == {"value": "line", "count": 1}
    assert any(item["type"] == "menu_without_page_view" and item["actor_user_id"] == "user_b" for item in result["breakpoints"])
    assert result["breakpoint_summary"]["menu_without_page_view"] == 1
    assert not any(item["type"] == "configuration_not_completed" for item in result["breakpoints"])
    assert result["timeline"]["items"][0]["event_id"] == "e7"


def test_navigation_and_global_analytics_endpoint_are_super_admin_only() -> None:
    with TemporaryDirectory() as tmpdir:
        server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
        server.services.interaction_event_store.write(
            tenant_id="tenant_demo", actor_user_id="u_reviewer", actor_account="reviewer@example.com",
            event_name="page_view", event_type="view", page_path="/weekly-report", page_name="经营周报",
        )
        server.services.interaction_event_store.write(
            tenant_id="tenant_other", actor_user_id="u_super_admin", actor_account="super@example.com",
            event_name="page_view", event_type="view", page_path="/dashboard", page_name="多机构分析",
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            super_nav_status, super_nav = _request(port, "/api/navigation", "u_super_admin", "tenant_demo")
            reviewer_nav_status, reviewer_nav = _request(port, "/api/navigation", "u_reviewer", "tenant_demo")
            denied_status, _ = _request(port, "/api/interaction-events/analytics?days=7", "u_reviewer", "tenant_demo")
            allowed_status, allowed = _request(port, "/api/interaction-events/analytics?days=7", "u_super_admin", "tenant_demo")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    assert super_nav_status == 200
    assert "task-workbench.interaction-analytics" in super_nav["menu_keys"]
    assert reviewer_nav_status == 200
    assert "task-workbench.interaction-analytics" not in reviewer_nav["menu_keys"]
    assert denied_status == 403
    assert allowed_status == 200
    assert allowed["tenant_id"] == "tenant_demo"
    assert allowed["scope"] == "global"
    assert allowed["summary"]["total_events"] == 2
    assert set(allowed["tenant_ids"]) == {"tenant_demo", "tenant_other"}
    assert {item["tenant_id"] for item in allowed["timeline"]["items"]} == {"tenant_demo", "tenant_other"}


def _event(
    event_id: str,
    actor_user_id: str,
    event_name: str,
    occurred_at: str,
    *,
    page_name: str = "",
    chart_name: str = "",
    extension: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "tenant_id": "tenant_test",
        "actor_user_id": actor_user_id,
        "actor_name": f"用户 {actor_user_id[-1].upper()}",
        "actor_account": f"{actor_user_id}@example.com",
        "event_name": event_name,
        "event_type": "view" if event_name == "page_view" else "click",
        "page_path": "/self-analysis/query" if page_name else "",
        "page_name": page_name,
        "chart_id": "chart_1" if chart_name else "",
        "chart_name": chart_name,
        "resource_type": "visualization" if chart_name else "",
        "resource_id": "chart_1" if chart_name else "",
        "extension": extension or {},
        "occurred_at": occurred_at,
    }


def _request(port: int, path: str, user_id: str, tenant_id: str) -> tuple[int, dict[str, object]]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.request("GET", path, headers={"X-User-Id": user_id, "X-Tenant-Id": tenant_id})
    response = connection.getresponse()
    raw = response.read().decode("utf-8")
    connection.close()
    return response.status, json.loads(raw) if raw else {}
