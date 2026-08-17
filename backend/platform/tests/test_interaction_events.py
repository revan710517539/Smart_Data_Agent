from __future__ import annotations

from types import SimpleNamespace

from backend.platform.api.router import API_ROUTE_REGISTRY
from backend.platform.api.routes.interaction_events import _require_explicit_session
from backend.platform.interaction_events import InMemoryInteractionEventStore, sanitize_interaction_extension
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


def test_interaction_event_route_requires_an_explicit_session() -> None:
    try:
        _require_explicit_session(SimpleNamespace(headers={}))
    except AuthenticationError as exc:
        assert str(exc) == "interaction_event_login_required"
    else:  # pragma: no cover
        raise AssertionError("anonymous telemetry writes must fail closed")

    _require_explicit_session(SimpleNamespace(headers={"Cookie": "sda_session=signed-session"}))


def test_recursive_sanitizer_limits_depth_and_collection_size() -> None:
    value = sanitize_interaction_extension({"items": list(range(100)), "nested": {"a": {"b": {"c": {"d": "hidden"}}}}})
    assert len(value["items"]) == 20
    assert "depth_limited" in str(value["nested"])
