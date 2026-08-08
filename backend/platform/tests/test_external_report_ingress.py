from __future__ import annotations

import http.client
import json
import os
import threading
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.platform.api.server import create_server
from backend.platform.ingestion.topic_data import TopicDataStore


def _request(port: int, path: str, payload: dict | None, *, token: str = "", user_id: str = "u_admin") -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"X-User-Id": user_id, "X-Tenant-Id": "tenant_demo"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
    connection.request(
        "POST" if payload is not None else "GET",
        path,
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None,
        headers=headers,
    )
    response = connection.getresponse()
    body = json.loads(response.read().decode("utf-8"))
    connection.close()
    return response.status, body


class ExternalReportIngressTest(unittest.TestCase):
    def test_token_bound_channel_upserts_visual_report_and_snapshot(self) -> None:
        bindings = json.dumps(
            {
                "bindings": [
                    {
                        "id": "workbuddy-local",
                        "token": "test-workbuddy-token",
                        "channel": "workbuddy",
                        "label": "WorkBuddy",
                        "tenant_id": "tenant_demo",
                        "user_id": "u_admin",
                    }
                ]
            }
        )
        with TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"SMART_DATA_AGENT_REPORT_INGRESS_BINDINGS_JSON": bindings}, clear=False):
            server = create_server("127.0.0.1", 0, f"{tmpdir}/platform.sqlite")
            server.services.topic_data_store = TopicDataStore(f"{tmpdir}/topic-data")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                payload = {
                    "source": {"channel": "workbuddy", "run_id": "session-001", "report_id": "customer-risk"},
                    "report": {
                        "title": "客户流失风险分析",
                        "query": "识别高价值客群风险",
                        "plan": "按AUM与活跃度分层",
                        "summary": "高AUM低活跃客群应优先跟进。",
                        "visual_types": {"primary": "bar", "secondary": "table"},
                        "rows": [{"客群": "高AUM低活跃", "风险分": 86}],
                    },
                }
                status, created = _request(server.server_address[1], "/api/integrations/reports", payload, token="test-workbuddy-token")
                self.assertEqual(status, 200)
                result = created["result"]
                self.assertEqual(created["channel"], "workbuddy")
                self.assertEqual(result["source"]["label"], "WorkBuddy")
                self.assertEqual(result["topicData"]["reference_type"], "report")

                updated_payload = {**payload, "report": {**payload["report"], "summary": "更新后的结论。"}}
                updated_status, updated = _request(server.server_address[1], "/api/integrations/reports", updated_payload, token="test-workbuddy-token")
                self.assertEqual(updated_status, 200)
                self.assertEqual(updated["result"]["id"], result["id"])

                weekly_status, weekly = _request(
                    server.server_address[1],
                    "/api/reports/analysis-result/save-weekly",
                    {"result_id": result["id"]},
                )
                self.assertEqual(weekly_status, 200)
                self.assertTrue(weekly["result"]["weeklyReportEligible"])
                self.assertTrue(weekly["result"]["weeklyReportSavedAt"])

                experience_status, experience = _request(
                    server.server_address[1],
                    "/api/reports/analysis-result/save-experience",
                    {"result_id": result["id"]},
                )
                self.assertEqual(experience_status, 200)
                self.assertEqual(experience["record"]["status"], "candidate")
                self.assertEqual(experience["record"]["subject_type"], "user")
                self.assertEqual(experience["record"]["subject_id"], "u_admin")
                self.assertEqual(experience["record"]["content"]["report"]["title"], "客户流失风险分析")
                self.assertEqual(experience["record"]["content"]["data_snapshot"]["rows"], [{"客群": "高AUM低活跃", "风险分": "86"}])
                repeat_status, repeat = _request(
                    server.server_address[1],
                    "/api/reports/analysis-result/save-experience",
                    {"result_id": result["id"]},
                )
                self.assertEqual(repeat_status, 200)
                self.assertTrue(repeat["idempotent"])

                list_status, listed = _request(server.server_address[1], "/api/reports/analysis-results", None)
                self.assertEqual(list_status, 200)
                self.assertEqual(listed["count"], 1)
                restored = listed["results"][0]
                self.assertEqual(restored["summary"], "更新后的结论。")
                self.assertEqual(restored["rows"], [{"客群": "高AUM低活跃", "风险分": "86"}])
                self.assertEqual(restored["source"]["channel"], "workbuddy")
                audit_actions = [event["action"] for event in server.services.audit_store.list("tenant_demo")]
                self.assertIn("external_report.import", audit_actions)
                self.assertIn("report.analysis.save_weekly", audit_actions)
                self.assertIn("report.analysis.save_experience", audit_actions)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_rejects_missing_or_wrong_channel_token(self) -> None:
        bindings = json.dumps({"bindings": [{"token": "test-workbuddy-token", "channel": "workbuddy", "tenant_id": "tenant_demo", "user_id": "u_admin"}]})
        with TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"SMART_DATA_AGENT_REPORT_INGRESS_BINDINGS_JSON": bindings}, clear=False):
            server = create_server("127.0.0.1", 0, f"{tmpdir}/platform.sqlite")
            server.services.topic_data_store = TopicDataStore(f"{tmpdir}/topic-data")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                payload = {"source": {"channel": "feishu", "run_id": "run-1"}, "report": {"title": "错误渠道"}}
                missing_status, _ = _request(server.server_address[1], "/api/integrations/reports", payload)
                self.assertEqual(missing_status, 401)
                mismatch_status, _ = _request(server.server_address[1], "/api/integrations/reports", payload, token="test-workbuddy-token")
                self.assertEqual(mismatch_status, 403)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
