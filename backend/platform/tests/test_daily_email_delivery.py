from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.platform.bootstrap import build_local_platform


class DailyEmailDeliveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.services = build_local_platform()

    def tearDown(self) -> None:
        self.services.close()

    def _save_report(self, *, publishable: bool = True) -> dict:
        evidence = (
            {
                "verified": True,
                "evidence_id": "ev_daily_1",
                "evidence_hash": "a" * 64,
                "source_snapshot": {"partition": "2026-07-10"},
            }
            if publishable
            else {}
        )
        return self.services.report_store.save_weekly_report_version(
            "tenant_demo",
            {
                "id": "weekly_source_ready" if publishable else "weekly_source_blocked",
                "reportId": "weekly_report_daily_source",
                "name": "日报来源周报",
                "savedAt": "2026-07-10T08:00:00+08:00",
                "report": {
                    "id": "weekly_report_daily_source",
                    "institutionName": "华兴银行",
                    "period": "2026年第28周",
                    "sections": [
                        {
                            "id": "performance",
                            "name": "经营表现",
                            "blocks": [
                                {
                                    "id": "verified_table",
                                    "type": "table",
                                    "title": "机构放款",
                                    "rows": [{"机构": "华东分行", "放款金额": 1200}],
                                    "evidenceRef": evidence,
                                },
                                {
                                    "id": "conclusion",
                                    "type": "text",
                                    "title": "经营结论",
                                    "content": "华东分行放款金额为 1200 万元，结论引用已验证数据块。",
                                    "contentItems": [],
                                },
                            ],
                        }
                    ],
                },
            },
            "u_admin",
        )

    def test_generation_requires_publishable_evidence_and_is_content_idempotent(self) -> None:
        self._save_report(publishable=False)
        with self.assertRaises(ValueError):
            self.services.daily_email_service.generate(
                "tenant_demo", "u_admin", source_report_version_id="weekly_source_blocked"
            )

        source = self._save_report(publishable=True)
        first = self.services.daily_email_service.generate(
            "tenant_demo", "u_admin", report_date="2026-07-10", source_report_version_id=source["id"]
        )
        second = self.services.daily_email_service.generate(
            "tenant_demo", "u_admin", report_date="2026-07-10", source_report_version_id=source["id"]
        )
        self.assertEqual(first["daily_report_run_id"], second["daily_report_run_id"])
        self.assertEqual(first["content_hash"], second["content_hash"])
        self.assertTrue(first["evidence_summary"]["publishable"])
        metadata, body = self.services.data_acquisition_service.get_artifact_content(
            "tenant_demo", first["body_artifact_id"]
        )
        self.assertEqual(metadata["content_hash"], first["content_hash"])
        self.assertIn("华东分行放款金额为 1200 万元", body.decode("utf-8"))

    def test_send_requires_email_subscription_and_records_real_delivery_receipt(self) -> None:
        source = self._save_report(publishable=True)
        run = self.services.daily_email_service.generate(
            "tenant_demo", "u_admin", report_date="2026-07-10", source_report_version_id=source["id"]
        )
        with self.assertRaises(ValueError):
            self.services.daily_email_service.send("tenant_demo", "u_admin", run["daily_report_run_id"])

        self.services.automation_store.create_subscription(
            "tenant_demo",
            {
                "subscription_name": "经营日报邮件",
                "event_types": ["report.daily.ready"],
                "channel_type": "email",
                "channel_config": {"recipient": "owner@example.com"},
            },
            "u_admin",
        )
        first = self.services.daily_email_service.send("tenant_demo", "u_admin", run["daily_report_run_id"])
        second = self.services.daily_email_service.send("tenant_demo", "u_admin", run["daily_report_run_id"])
        self.assertEqual(first["outbox_event_id"], second["outbox_event_id"])
        self.assertEqual(first["status"], "queued")

        with patch("backend.platform.automation.runtime._deliver", return_value="provider-message-1"):
            self.services.automation_runtime.process_notifications_once()
        state = self.services.daily_email_service.state("tenant_demo", "u_admin")
        self.assertEqual(state["latest"]["status"], "delivered")
        self.assertEqual(state["delivery_summary"], {"delivered": 1})
        email_row = self.services.automation_store._conn.execute(
            "SELECT * FROM platform_email_messages WHERE tenant_id = ?",
            ("tenant_demo",),
        ).fetchone()
        self.assertIsNotNone(email_row)
        self.assertEqual(email_row["body_artifact_id"], run["body_artifact_id"])
        self.assertNotIn("华东分行放款金额", email_row["provider_response"])

    def test_email_adapter_reads_verified_html_from_artifact_instead_of_copying_body_into_event(self) -> None:
        source = self._save_report(publishable=True)
        run = self.services.daily_email_service.generate(
            "tenant_demo", "u_admin", report_date="2026-07-10", source_report_version_id=source["id"]
        )
        subscription = {
            "channel_type": "email",
            "channel_config": {"recipient": "owner@example.com"},
        }
        event = {
            "tenant_id": "tenant_demo",
            "outbox_event_id": "event-daily",
            "event_type": "report.daily.ready",
            "payload": {
                "subject": run["subject"],
                "body_artifact_id": run["body_artifact_id"],
                "body_hash": run["content_hash"],
            },
        }
        sent_messages = []

        class FakeSMTP:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def login(self, username, password):
                return None

            def send_message(self, message):
                sent_messages.append(message)

        from backend.platform.automation.runtime import _deliver

        with patch.dict(
            "os.environ",
            {
                "SMART_DATA_AGENT_SMTP_HOST": "smtp.example.com",
                "SMART_DATA_AGENT_SMTP_FROM": "reports@example.com",
            },
        ), patch("backend.platform.automation.runtime.validate_outbound_url", return_value="https://smtp.example.com"), patch(
            "backend.platform.automation.runtime.smtplib.SMTP_SSL", FakeSMTP
        ):
            provider_id = _deliver(
                subscription,
                event,
                self.services.data_acquisition_service.get_artifact_content,
            )
        self.assertTrue(provider_id)
        self.assertEqual(len(sent_messages), 1)
        message_text = sent_messages[0].as_string()
        self.assertIn("text/html", message_text)
        self.assertNotIn("body_hash\":", message_text)


if __name__ == "__main__":
    unittest.main()
