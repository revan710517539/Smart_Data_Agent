from __future__ import annotations

import json
import unittest

from backend.platform.bootstrap import build_local_platform


class MarketMonitoringTest(unittest.TestCase):
    def setUp(self) -> None:
        self.services = build_local_platform()
        self.source_system = self.services.data_acquisition_service.create_source(
            "tenant_demo",
            {
                "source_code": "licensed_market_feed",
                "source_name": "持牌市场数据源",
                "source_category": "market",
                "license_metadata": {
                    "license_type": "licensed_feed",
                    "contract_ref": "contract-market-2026",
                },
            },
            "u_admin",
        )
        self.market_source = self.services.market_service.create_source(
            "tenant_demo",
            {
                "source_system_id": self.source_system["source_system_id"],
                "publisher": "市场数据出版社",
                "acquisition_method": "licensed_feed",
                "license_type": "licensed_feed",
                "reliability_score": 0.95,
            },
            "u_admin",
        )
        self.entity = self.services.market_service.create_entity(
            "tenant_demo",
            {
                "entity_type": "institution",
                "entity_code": "competitor_a",
                "entity_name": "竞品银行A",
                "attributes": {"region": "华东"},
            },
            "u_admin",
        )

    def tearDown(self) -> None:
        self.services.close()

    def _artifact(self, name: str, status: str = "active") -> dict:
        content = json.dumps({"source_record": name}, ensure_ascii=False).encode()
        stored = self.services.data_acquisition_service.object_store.put("tenant_demo", content, ".json")
        return self.services.data_acquisition_store.create_artifact(
            "tenant_demo",
            object_uri=stored.object_uri,
            content_hash=stored.content_hash,
            content_type="application/json",
            size_bytes=stored.size_bytes,
            status=status,
            created_by="u_admin",
            artifact_type="json",
        )

    def test_observation_requires_active_evidence_and_change_rule_creates_one_auditable_event(self) -> None:
        prior_artifact = self._artifact("prior")
        current_artifact = self._artifact("current")
        common = {
            "market_source_id": self.market_source["market_source_id"],
            "market_entity_id": self.entity["market_entity_id"],
            "metric_code": "deposit_rate",
            "unit": "%",
            "confidence": 0.95,
        }
        prior = self.services.market_service.create_observation(
            "tenant_demo",
            {
                **common,
                "observed_at": "2026-07-09T02:00:00Z",
                "value_numeric": 2.0,
                "evidence_artifact_id": prior_artifact["artifact_id"],
                "source_record_id": "record-prior",
            },
            "u_admin",
        )
        current = self.services.market_service.create_observation(
            "tenant_demo",
            {
                **common,
                "observed_at": "2026-07-10T02:00:00Z",
                "value_numeric": 2.4,
                "evidence_artifact_id": current_artifact["artifact_id"],
                "source_record_id": "record-current",
            },
            "u_admin",
        )
        duplicate = self.services.market_service.create_observation(
            "tenant_demo",
            {
                **common,
                "observed_at": "2026-07-10T02:00:00Z",
                "value_numeric": 999,
                "evidence_artifact_id": current_artifact["artifact_id"],
                "source_record_id": "record-current",
            },
            "u_admin",
        )
        self.assertEqual(duplicate["market_observation_id"], current["market_observation_id"])
        rule = self.services.market_service.create_rule(
            "tenant_demo",
            {
                "rule_name": "存款利率上升超过10%",
                "entity_selector": {"entity_types": ["institution"], "attributes": {"region": "华东"}},
                "metric_code": "deposit_rate",
                "condition_expression": {"operator": "change_pct_gt", "threshold": 10},
                "severity": "warning",
                "cooldown_seconds": 3600,
            },
            "u_admin",
        )
        first = self.services.market_service.evaluate("tenant_demo", rule["market_rule_id"])
        second = self.services.market_service.evaluate("tenant_demo", rule["market_rule_id"])
        self.assertEqual(first["created_count"], 1)
        self.assertEqual(second["created_count"], 0)
        event = first["created_events"][0]
        self.assertEqual(event["observation_id"], current["market_observation_id"])
        self.assertEqual(event["evidence"]["previous_observation_id"], prior["market_observation_id"])
        self.assertEqual(event["evidence"]["evidence_hash"], current_artifact["content_hash"])
        self.assertEqual(event["evidence"]["license_type"], "licensed_feed")
        listed = self.services.market_service.bundle("tenant_demo")["observations"]
        self.assertEqual(listed[0]["market_observation_id"], current["market_observation_id"])
        self.assertEqual(listed[0]["publisher"], "市场数据出版社")
        self.assertEqual(listed[0]["evidence_hash"], current_artifact["content_hash"])
        resolved = self.services.market_store.update_event_status(
            "tenant_demo", event["market_event_id"], "resolved", "u_reviewer"
        )
        self.assertEqual(resolved["status"], "resolved")

    def test_quarantined_artifact_and_cross_tenant_source_are_rejected(self) -> None:
        quarantined = self._artifact("quarantined", status="quarantined")
        with self.assertRaises(ValueError):
            self.services.market_service.create_observation(
                "tenant_demo",
                {
                    "market_source_id": self.market_source["market_source_id"],
                    "market_entity_id": self.entity["market_entity_id"],
                    "metric_code": "deposit_rate",
                    "observed_at": "2026-07-10T02:00:00Z",
                    "value_numeric": 2.4,
                    "evidence_artifact_id": quarantined["artifact_id"],
                    "source_record_id": "bad-record",
                },
                "u_admin",
            )
        with self.assertRaises(KeyError):
            self.services.market_store.get_source("tenant_other", self.market_source["market_source_id"])

    def test_market_events_flow_through_outbox_subscriptions(self) -> None:
        subscription = self.services.automation_store.create_subscription(
            "tenant_demo",
            {
                "subscription_name": "市场事件站内提醒",
                "event_types": ["market.monitoring.triggered"],
                "channel_type": "in_app",
                "channel_config": {},
            },
            "u_admin",
        )
        artifact = self._artifact("threshold")
        self.services.market_service.create_observation(
            "tenant_demo",
            {
                "market_source_id": self.market_source["market_source_id"],
                "market_entity_id": self.entity["market_entity_id"],
                "metric_code": "market_share",
                "observed_at": "2026-07-10T02:00:00Z",
                "value_numeric": 30,
                "unit": "%",
                "evidence_artifact_id": artifact["artifact_id"],
                "source_record_id": "market-share-1",
            },
            "u_admin",
        )
        rule = self.services.market_service.create_rule(
            "tenant_demo",
            {
                "rule_name": "市场份额阈值",
                "entity_selector": {"entity_ids": [self.entity["market_entity_id"]]},
                "metric_code": "market_share",
                "condition_expression": {"operator": "gt", "threshold": 20},
                "severity": "critical",
            },
            "u_admin",
        )
        self.services.market_service.evaluate("tenant_demo", rule["market_rule_id"])
        self.services.automation_runtime.process_notifications_once()
        self.services.automation_runtime.process_notifications_once()
        deliveries = self.services.automation_store.list_in_app_deliveries("tenant_demo", "u_admin")
        self.assertEqual(deliveries[0]["subscription_id"], subscription["subscription_id"])
        self.assertEqual(deliveries[0]["event_type"], "market.monitoring.triggered")


if __name__ == "__main__":
    unittest.main()
