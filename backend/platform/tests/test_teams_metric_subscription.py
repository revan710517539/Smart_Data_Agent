from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.platform.automation.metric_subscription import collect_metric_snapshot, render_teams_metric_markdown
from backend.platform.api.routes.automation import (
    handle_teams_connection_auth_poll,
    handle_teams_connection_auth_start,
    handle_teams_metric_subscription_auth_poll,
    handle_teams_metric_subscription_auth_start,
    handle_teams_metric_subscription_enable,
    handle_teams_metric_subscription_test,
)
from backend.platform.bootstrap import build_local_platform
from backend.platform.integrations.teams import complete_device_authorization, send_markdown_to_self
from backend.platform.metrics.defaults import teams_subscription_test_metrics


class _Response:
    status = 200

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def read(self, _limit: int = -1) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class TeamsMetricSubscriptionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.services = build_local_platform()

    def tearDown(self) -> None:
        self.services.close()

    def test_teams_self_subscription_is_encrypted_and_delivery_is_idempotent(self) -> None:
        subscription = self.services.automation_store.create_subscription(
            "tenant_demo",
            {
                "subscription_name": "放款金额每日指标",
                "event_types": ["metric.daily.snapshot.ready"],
                "channel_type": "webhook",
                "channel_config": {"provider": "360teams_self", "access_token": "test-token"},
            },
            "u_admin",
        )
        self.assertEqual(subscription["channel_provider"], "360teams_self")
        self.assertEqual(subscription["channel_config"], {"configured": True})
        raw = self.services.automation_store._conn.execute(
            "SELECT channel_config_secret FROM platform_subscriptions WHERE tenant_id = ? AND subscription_id = ?",
            ("tenant_demo", subscription["subscription_id"]),
        ).fetchone()[0]
        self.assertNotIn("test-token", raw)
        event_id = self.services.automation_store.enqueue_outbox_event(
            "tenant_demo", "metric_subscription", subscription["subscription_id"], "metric.daily.snapshot.ready",
            {"metric_name": "放款金额", "value": 120, "period": "2026-08-05", "unit": "万元"}, event_key="teams-metric-test",
        )
        with patch("backend.platform.integrations.teams.send_markdown_to_self", return_value="teams-message-1") as deliver:
            self.services.automation_runtime.process_notifications_once()
            self.services.automation_runtime.process_notifications_once()
        self.assertEqual(deliver.call_count, 1)
        delivery = self.services.automation_store.list_deliveries_for_outbox("tenant_demo", event_id)[0]
        self.assertEqual(delivery["status"], "delivered")
        self.assertEqual(delivery["provider_message_id"], "teams-message-1")
        self.assertEqual(self.services.automation_store.list_in_app_deliveries("tenant_demo", "u_admin")[0]["channel_type"], "webhook")

    def test_provider_uses_fixed_self_endpoint_and_markdown_payload(self) -> None:
        with patch("backend.platform.integrations.teams.validate_outbound_url", side_effect=lambda value, **_kwargs: value), patch(
            "backend.platform.integrations.teams.safe_urlopen", return_value=_Response({"code": 0, "data": {"messageId": "msg-1"}})
        ) as open_request:
            provider_id = send_markdown_to_self("safe-token", "每日指标", "**放款金额**：120万元")
        self.assertEqual(provider_id, "msg-1")
        request = open_request.call_args.args[0]
        self.assertEqual(request.full_url, "https://sk.360teams.com/api/rce-app/publish/private/message/self")
        self.assertEqual(request.get_header("Authorization"), "safe-token")
        self.assertIn("Chrome/124.0.0.0", request.get_header("User-agent") or "")
        self.assertIn("markdown", request.data.decode("utf-8"))

    def test_device_poll_keeps_waiting_for_pending_authorization(self) -> None:
        with patch("backend.platform.integrations.teams.validate_outbound_url", side_effect=lambda value, **_kwargs: value), patch(
            "backend.platform.integrations.teams.safe_urlopen", return_value=_Response({"code": 10230, "data": {}})
        ):
            self.assertIsNone(complete_device_authorization("pending-device-code"))

    def test_snapshot_uses_authorized_semantic_query_and_renders_plain_conclusion(self) -> None:
        captured = {}

        class Semantic:
            def query(self, request):
                captured["request"] = request
                return type("Result", (), {"data": [{"stat_date": "2026-08-04", "loan_amount": 100}, {"stat_date": "2026-08-05", "loan_amount": 120}]})()

        snapshot = collect_metric_snapshot(
            type("Services", (), {"semantic_service": Semantic()})(),
            "tenant_demo", "u_admin",
            {"metricId": "M-loan", "metricName": "放款金额", "metricCode": "loan_amount", "datasetId": "loans", "timeDimension": "stat_date", "unit": "万元"},
        )
        self.assertEqual(captured["request"].tenant_id, "tenant_demo")
        self.assertEqual(snapshot["value"], 120.0)
        self.assertEqual(snapshot["delta"], 20.0)
        title, markdown = render_teams_metric_markdown(snapshot)
        self.assertIn("放款金额", title)
        self.assertIn("较上一期：+20万元", markdown)

    def test_multi_metric_template_preserves_order_and_constrained_style(self) -> None:
        title, markdown = render_teams_metric_markdown(
            {
                "snapshots": [
                    {"metric_id": "M-loan", "metric_name": "放款金额", "value": 120, "unit": "万元", "period": "2026-08-05", "previous_value": 100, "delta": 20},
                    {"metric_id": "M-deposit", "metric_name": "存款余额", "value": 88, "unit": "万元", "period": "2026-08-05"},
                ],
                "message_template": {
                    "title": "经营日报",
                    "subtitle": "华兴银行 · T+1",
                    "footer": "仅本人可见",
                    "metrics": [
                        {"metricId": "M-deposit", "fontSize": "large", "color": "green"},
                        {"metricId": "M-loan", "fontSize": "small", "color": "blue"},
                    ],
                },
            }
        )
        self.assertEqual(title, "经营日报")
        self.assertLess(markdown.index("存款余额"), markdown.index("放款金额"))
        self.assertIn("🟢", markdown)
        self.assertIn("🔵", markdown)
        self.assertIn("仅本人可见", markdown)

    def test_editable_template_body_replaces_metric_placeholder_in_place(self) -> None:
        _title, markdown = render_teams_metric_markdown(
            {
                "snapshots": [{"metric_id": "M-loan", "metric_name": "放款金额", "value": 120, "unit": "万元", "period": "2026-08-05", "previous_value": 100, "delta": 20}],
                "message_template": {
                    "title": "自定义日报",
                    "bodyHtml": "<h2>经营重点</h2><p>今日关注：{{metric:M-loan}}</p><p>请及时跟进。</p>",
                },
            }
        )
        self.assertLess(markdown.index("今日关注："), markdown.index("放款金额：120万元"))
        self.assertLess(markdown.index("放款金额：120万元"), markdown.index("请及时跟进。"))
        self.assertIn("较上一期：+20万元", markdown)

    def test_template_renders_the_fixed_smart_data_agent_pc_link_only(self) -> None:
        _title, markdown = render_teams_metric_markdown(
            {
                "snapshots": [{"metric_id": "M-loan", "metric_name": "放款金额", "value": 120, "unit": "万元", "period": "2026-08-05"}],
                "message_template": {
                    "bodyHtml": (
                        '<p>详情请在 PC 端点击：<a href="https://xujingbo-smart-data-agent.qifudigitech.com/notifications/subscriptions">'
                        "Smart Data Agent</a></p><p><a href=\"https://untrusted.example\">不可信链接</a></p>"
                    ),
                },
            }
        )
        self.assertIn("[Smart Data Agent](https://xujingbo-smart-data-agent.qifudigitech.com/notifications/subscriptions)", markdown)
        self.assertIn("不可信链接", markdown)
        self.assertNotIn("https://untrusted.example", markdown)

    def test_system_test_metrics_are_executable_without_customer_data(self) -> None:
        amount, customers = teams_subscription_test_metrics()
        amount_snapshot = collect_metric_snapshot(self.services, "tenant_demo", "u_admin", amount)
        customer_snapshot = collect_metric_snapshot(self.services, "tenant_demo", "u_admin", customers)
        self.assertTrue(amount_snapshot["is_test_metric"])
        self.assertEqual(amount_snapshot["metric_name"], "【测试】经营金额")
        self.assertEqual(customer_snapshot["metric_name"], "【测试】活跃客户数")

    def test_authorization_poll_creates_owned_task_without_returning_token(self) -> None:
        self.services.metric_dictionary_store.upsert(
            "tenant_demo",
            {"metricId": "M-teams", "metricName": "放款金额", "metricCode": "loan_amount", "datasetId": "loans", "timeDimension": "stat_date", "unit": "万元", "aggregationType": "sum", "semanticVersion": "1", "visibleInstitutions": ["全部机构"]},
            updated_by="u_admin",
        )

        class Handler:
            services = self.services
            payload = {"metric_id": "M-teams", "subscription_name": "放款金额每日指标", "schedule_expression": "0 9 * * *", "device_code": "device-code"}
            response = None
            def _read_json(self): return self.payload
            def _request_context(self, **_kwargs): return SimpleNamespace(tenant_id="tenant_demo", user_id="u_admin")
            def _require_notification_permission(self, *_args): return None
            def _require_metric_permission(self, *_args): return None
            def _write_audit(self, *_args): return None
            def _send_json(self, payload, *_args): self.response = payload

        handler = Handler()
        with patch("backend.platform.api.routes.automation.start_device_authorization", return_value={"device_code": "device-code", "sso_url": "https://login.example"}):
            handle_teams_metric_subscription_auth_start(handler)
        self.assertEqual(handler.response["authorization"]["sso_url"], "https://login.example")
        with patch("backend.platform.api.routes.automation.complete_device_authorization", return_value="not-returned-token"):
            handle_teams_metric_subscription_auth_poll(handler)
        self.assertTrue(handler.response["completed"])
        self.assertNotIn("not-returned-token", json.dumps(handler.response, ensure_ascii=False))
        task = handler.response["automation_task"]
        self.assertEqual(task["handler_ref"], "metric.subscription.snapshot")
        saved = self.services.automation_store.get_subscription("tenant_demo", handler.response["subscription"]["subscription_id"], reveal_config=True)
        self.assertEqual(saved["channel_config"]["provider"], "360teams_self")

    def test_standalone_connection_is_owner_scoped_and_enable_requires_its_token(self) -> None:
        self.services.metric_dictionary_store.upsert(
            "tenant_demo",
            {"metricId": "M-connected", "metricName": "存款余额", "metricCode": "deposit_balance", "datasetId": "deposits", "timeDimension": "stat_date", "unit": "万元", "aggregationType": "sum", "semanticVersion": "1", "visibleInstitutions": ["全部机构"]},
            updated_by="u_admin",
        )

        class Handler:
            services = self.services
            payload: dict = {}
            response = None
            def _read_json(self): return self.payload
            def _request_context(self, **_kwargs): return SimpleNamespace(tenant_id="tenant_demo", user_id="u_admin")
            def _require_notification_permission(self, *_args): return None
            def _require_metric_permission(self, *_args): return None
            def _write_audit(self, *_args): return None
            def _send_json(self, payload, *_args): self.response = payload

        handler = Handler()
        with patch("backend.platform.api.routes.automation.start_device_authorization", return_value={"device_code": "connection-device", "sso_url": "https://login.example"}):
            handle_teams_connection_auth_start(handler)
        self.assertEqual(handler.response["authorization"]["device_code"], "connection-device")
        handler.payload = {"device_code": "connection-device"}
        with patch("backend.platform.api.routes.automation.complete_device_authorization", return_value="connection-secret-token"):
            handle_teams_connection_auth_poll(handler)
        self.assertEqual(handler.response["connection"], {"connected": True, "provider": "360teams_self"})
        self.assertNotIn("connection-secret-token", json.dumps(handler.response, ensure_ascii=False))
        self.assertEqual(self.services.automation_store.list_subscriptions("tenant_demo", "u_admin"), [])
        connection = self.services.automation_store.get_teams_connection("tenant_demo", "u_admin", reveal_config=True)
        self.assertEqual(connection["channel_config"]["access_token"], "connection-secret-token")

        handler.payload = {"metric_id": "M-connected", "subscription_name": "存款余额每日快报", "schedule_expression": "0 9 * * *"}
        handle_teams_metric_subscription_enable(handler)
        self.assertEqual(handler.response["subscription"]["channel_provider"], "360teams_self")
        self.assertEqual(handler.response["automation_task"]["handler_ref"], "metric.subscription.snapshot")

    def test_enable_accepts_multiple_metrics_and_persists_template(self) -> None:
        for metric_id, metric_name, metric_code in (("M-one", "放款金额", "loan_amount"), ("M-two", "存款余额", "deposit_balance")):
            self.services.metric_dictionary_store.upsert(
                "tenant_demo",
                {"metricId": metric_id, "metricName": metric_name, "metricCode": metric_code, "datasetId": "daily_metrics", "timeDimension": "stat_date", "unit": "万元", "aggregationType": "sum", "semanticVersion": "1", "visibleInstitutions": ["全部机构"]},
                updated_by="u_admin",
            )
        self.services.automation_store.upsert_teams_connection("tenant_demo", "u_admin", "connection-secret-token")

        class Handler:
            services = self.services
            payload = {
                "metric_ids": ["M-two", "M-one"],
                "subscription_name": "经营双指标日报",
                "schedule_expression": "0 9 * * *",
                "message_template": {"title": "经营日报", "metrics": [{"metricId": "M-two", "fontSize": "large", "color": "green"}, {"metricId": "M-one", "fontSize": "normal", "color": "blue"}]},
            }
            response = None
            def _read_json(self): return self.payload
            def _request_context(self, **_kwargs): return SimpleNamespace(tenant_id="tenant_demo", user_id="u_admin")
            def _require_notification_permission(self, *_args): return None
            def _require_metric_permission(self, *_args): return None
            def _write_audit(self, *_args): return None
            def _send_json(self, payload, *_args): self.response = payload

        handler = Handler()
        handle_teams_metric_subscription_enable(handler)
        task_config = handler.response["automation_task"]["task_config"]
        self.assertEqual([metric["metricId"] for metric in task_config["metrics"]], ["M-two", "M-one"])
        self.assertEqual(task_config["message_template"]["metrics"][0]["color"], "green")

    def test_test_send_uses_current_template_without_creating_subscription_or_task(self) -> None:
        self.services.automation_store.upsert_teams_connection("tenant_demo", "u_admin", "connection-secret-token")

        class Handler:
            services = self.services
            payload = {
                "metric_ids": ["SYS_TEAMS_TEST_AMOUNT", "SYS_TEAMS_TEST_CUSTOMERS"],
                "subscription_name": "Teams 联调测试",
                "message_template": {"title": "Teams 联调", "bodyHtml": "<p>金额：{{metric:SYS_TEAMS_TEST_AMOUNT}}</p><p>客户：{{metric:SYS_TEAMS_TEST_CUSTOMERS}}</p>"},
            }
            response = None
            def _read_json(self): return self.payload
            def _request_context(self, **_kwargs): return SimpleNamespace(tenant_id="tenant_demo", user_id="u_admin")
            def _require_notification_permission(self, *_args): return None
            def _require_metric_permission(self, *_args): return None
            def _write_audit(self, *_args): return None
            def _send_json(self, payload, *_args): self.response = payload

        handler = Handler()
        with patch("backend.platform.api.routes.automation.send_markdown_to_self", return_value="teams-test-message") as send:
            handle_teams_metric_subscription_test(handler)
        self.assertTrue(handler.response["sent"])
        self.assertEqual(handler.response["provider_message_id"], "teams-test-message")
        self.assertEqual(send.call_count, 1)
        self.assertIn("【测试】经营金额", send.call_args.args[2])
        self.assertEqual(self.services.automation_store.list_subscriptions("tenant_demo", "u_admin"), [])
        self.assertEqual(self.services.automation_store.list_tasks("tenant_demo"), [])


if __name__ == "__main__":
    unittest.main()
