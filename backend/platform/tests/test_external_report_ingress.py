from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.platform.api.server import create_server
from backend.platform.ingestion.topic_data import TopicDataStore


def _request(port: int, path: str, payload: dict | None, *, token: str = "", user_id: str = "u_super_admin") -> tuple[int, dict]:
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
    def test_cli_end_to_end_for_workbuddy_codex_and_qwork(self) -> None:
        channels = ("workbuddy", "codex", "qwork")
        bindings = json.dumps({"bindings": [
            {"id": f"{channel}-e2e", "token": f"{channel}-e2e-token", "channel": channel, "tenant_id": "tenant_demo", "user_id": "u_super_admin"}
            for channel in channels
        ]})
        cli = Path(__file__).resolve().parents[3] / "integrations/workbuddy-smart-data-report/bin/sda_report.py"
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "csv"
            tenant_dir = root / "tenant_demo"
            tenant_dir.mkdir(parents=True)
            (tenant_dir / "authorized.csv").write_text("机构,金额\nA,10\nB,20\n", encoding="utf-8")
            with patch.dict(os.environ, {"SMART_DATA_AGENT_REPORT_INGRESS_BINDINGS_JSON": bindings, "SMART_DATA_AGENT_DATA_CRAWLER_ROOT": str(root)}, clear=False):
                server = create_server("127.0.0.1", 0, f"{tmpdir}/platform.sqlite")
                server.services.topic_data_store = TopicDataStore(f"{tmpdir}/topic-data")
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    catalog = server.services.data_acquisition_service.csv_source.for_tenant("tenant_demo")
                    catalog.prime_catalog()
                    table = catalog.table_assets()[0]
                    server.services.data_asset_store.set_raw_table_external_reference(
                        "tenant_demo", table["sourceKey"], "shared", table["schemaFingerprint"], "u_super_admin",
                    )
                    config = Path(tmpdir) / "report-cli.json"
                    config.write_text(json.dumps({"endpoint": f"http://127.0.0.1:{server.server_address[1]}"}), encoding="utf-8")

                    def run_cli(channel: str, *arguments: str) -> dict:
                        environment = os.environ.copy()
                        environment["SMART_DATA_AGENT_REPORT_TOKEN"] = f"{channel}-e2e-token"
                        completed = subprocess.run(
                            [sys.executable, str(cli), *arguments, "--config", str(config), "--json"],
                            check=True,
                            text=True,
                            capture_output=True,
                            env=environment,
                        )
                        return json.loads(completed.stdout)

                    for channel in channels:
                        context = run_cli(channel, "bridge", "--channel", channel, "context")
                        self.assertEqual(context["raw_tables"][0]["sourceKey"], table["sourceKey"])
                        data = run_cli(channel, "bridge", "--channel", channel, "data", "--source-key", table["sourceKey"], "--columns", "机构,金额", "--limit", "2")
                        self.assertEqual(data["row_count"], 2)
                        self.assertFalse(data["truncated"])
                        report_file = Path(tmpdir) / f"{channel}-report.json"
                        report_file.write_text(json.dumps({
                            "source": {"channel": channel, "run_id": f"{channel}-run", "report_id": "authorized-analysis"},
                            "report": {"title": f"{channel}授权表分析", "query": "机构金额", "plan": "按机构汇总", "summary": "B高于A", "rows": [{"机构": "B", "金额": 20}]},
                        }, ensure_ascii=False), encoding="utf-8")
                        published = run_cli(channel, "publish", "--channel", channel, "--input", str(report_file))
                        self.assertEqual(published["channel"], channel)
                        evidence_file = Path(tmpdir) / f"{channel}-evidence.json"
                        evidence_file.write_text(json.dumps({
                            "run_id": f"{channel}-run",
                            "report_id": published["result"]["id"],
                            "references": [{"source_key": table["sourceKey"], "schema_fingerprint": table["schemaFingerprint"], "columns": ["机构", "金额"]}],
                            "title": f"{channel}授权表分析",
                            "question": "机构金额",
                            "summary": "B高于A",
                            "methodology": "按机构汇总并比较",
                            "logic_steps": ["读取授权表", "按机构汇总", "比较金额"],
                            "findings": ["B高于A"],
                            "limitations": ["样本仅两行"],
                            "metrics": ["金额"],
                            "dimensions": ["机构"],
                        }, ensure_ascii=False), encoding="utf-8")
                        evidence = run_cli(channel, "bridge", "--channel", channel, "evidence", "--input", str(evidence_file))
                        self.assertTrue(evidence["accepted"])
                        self.assertTrue(evidence["review_required"])
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

    def test_three_bridge_channels_read_only_shared_csv_and_return_review_only_evidence(self) -> None:
        bindings = json.dumps({"bindings": [
            {"id": f"{channel}-local", "token": f"test-{channel}-token", "channel": channel, "tenant_id": "tenant_demo", "user_id": "u_super_admin"}
            for channel in ("workbuddy", "codex", "qwork")
        ]})
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "csv"
            tenant_dir = root / "tenant_demo"
            tenant_dir.mkdir(parents=True)
            (tenant_dir / "weekly.csv").write_text("机构,金额\nA,10\n", encoding="utf-8")
            with patch.dict(os.environ, {"SMART_DATA_AGENT_REPORT_INGRESS_BINDINGS_JSON": bindings, "SMART_DATA_AGENT_DATA_CRAWLER_ROOT": str(root)}, clear=False):
                server = create_server("127.0.0.1", 0, f"{tmpdir}/platform.sqlite")
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    catalog = server.services.data_acquisition_service.csv_source.for_tenant("tenant_demo")
                    catalog.prime_catalog()
                    table = catalog.table_assets()[0]
                    status, before = _request(server.server_address[1], "/api/integrations/workbuddy/context", None, token="test-workbuddy-token")
                    self.assertEqual(status, 200)
                    self.assertEqual(before["raw_tables"], [])
                    server.services.data_asset_store.set_raw_table_external_reference(
                        "tenant_demo", table["sourceKey"], "shared", table["schemaFingerprint"], "u_super_admin",
                    )
                    evidence_memory_ids: dict[str, str] = {}
                    for channel in ("workbuddy", "codex", "qwork"):
                        token = f"test-{channel}-token"
                        status, context = _request(server.server_address[1], f"/api/integrations/{channel}/context", None, token=token)
                        self.assertEqual(status, 200)
                        self.assertEqual(context["channel"], channel)
                        self.assertEqual(context["raw_tables"][0]["sourceKey"], table["sourceKey"])
                        status, data = _request(server.server_address[1], f"/api/integrations/{channel}/data", {"source_key": table["sourceKey"], "limit": 1}, token=token)
                        self.assertEqual(status, 200)
                        self.assertEqual(data["rows"], [{"机构": "A", "金额": "10"}])
                        status, evidence = _request(
                            server.server_address[1],
                            f"/api/integrations/{channel}/evidence",
                            {
                                "references": [{"source_key": table["sourceKey"], "schema_fingerprint": table["schemaFingerprint"], "columns": ["机构", "金额"]}],
                                "run_id": f"{channel}-run-1",
                                "title": "周报分析",
                                "question": "各机构金额表现如何？",
                                "summary": "金额保持稳定。",
                                "methodology": "按机构汇总金额并核对口径。",
                                "analysis_content": "A机构金额为10，样本仅覆盖当前授权表。",
                                "logic_steps": ["读取授权表", "按机构汇总", "核对结果"],
                                "findings": ["A机构金额为10"],
                                "metrics": ["金额"],
                                "dimensions": ["机构"],
                            },
                            token=token,
                        )
                        self.assertEqual(status, 200)
                        self.assertTrue(evidence["accepted"])
                        self.assertTrue(evidence["review_required"])
                        self.assertIsNotNone(evidence["memory_candidate_id"])
                        evidence_memory_ids[channel] = evidence["memory_candidate_id"]
                        candidate = server.services.memory_service.get("tenant_demo", evidence["memory_candidate_id"])
                        material = candidate["content"]["evidence"]
                        self.assertEqual(material["channel"], channel)
                        self.assertEqual(material["logic_steps"], ["读取授权表", "按机构汇总", "核对结果"])
                        self.assertEqual(material["references"][0]["source_key"], table["sourceKey"])
                        self.assertEqual(material["references"][0]["columns"], ["机构", "金额"])
                    second_status, second_evidence = _request(
                        server.server_address[1],
                        "/api/integrations/codex/evidence",
                        {
                            "references": [{"source_key": table["sourceKey"], "schema_fingerprint": table["schemaFingerprint"], "columns": ["机构", "金额"]}],
                            "run_id": "codex-run-2",
                            "title": "周报分析复核",
                            "question": "各机构金额表现如何？",
                            "summary": "第二次分析继续显示金额稳定。",
                            "methodology": "按机构汇总金额并复核口径。",
                            "logic_steps": ["读取授权表", "按机构汇总", "复核金额"],
                            "findings": ["A机构金额为10"],
                            "metrics": ["金额"],
                            "dimensions": ["机构"],
                        },
                        token="test-codex-token",
                    )
                    self.assertEqual(second_status, 200)
                    self.assertIsNotNone(second_evidence["skill_candidate_id"])
                    learned_skill = server.services.data_asset_store.get_item(
                        "tenant_demo", "analysis_skill", second_evidence["skill_candidate_id"],
                    )
                    self.assertIn(evidence_memory_ids["codex"], learned_skill["memoryRefs"])
                    self.assertIn(second_evidence["memory_candidate_id"], learned_skill["memoryRefs"])
                    self.assertIn("按机构汇总", json.dumps(learned_skill["learnedProcedure"], ensure_ascii=False))
                    forbidden_status, _ = _request(
                        server.server_address[1],
                        "/api/integrations/codex/evidence",
                        {"source_key": table["sourceKey"], "schema_fingerprint": table["schemaFingerprint"], "run_id": "bad-run", "summary": "摘要", "methodology": "方法", "transcript": "不应上传"},
                        token="test-codex-token",
                    )
                    self.assertEqual(forbidden_status, 400)
                    invalid_data_status, _ = _request(
                        server.server_address[1],
                        "/api/integrations/codex/data",
                        {"source_key": table["sourceKey"], "columns": ["不存在字段"], "limit": 1},
                        token="test-codex-token",
                    )
                    self.assertEqual(invalid_data_status, 400)
                    missing_columns_status, _ = _request(
                        server.server_address[1],
                        "/api/integrations/codex/evidence",
                        {
                            "references": [{"source_key": table["sourceKey"], "schema_fingerprint": table["schemaFingerprint"]}],
                            "run_id": "missing-columns",
                            "summary": "摘要",
                            "methodology": "方法",
                        },
                        token="test-codex-token",
                    )
                    self.assertEqual(missing_columns_status, 400)
                    wrong_channel_status, _ = _request(server.server_address[1], "/api/integrations/qwork/context", None, token="test-codex-token")
                    self.assertEqual(wrong_channel_status, 403)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

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
                        "user_id": "u_super_admin",
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
                self.assertEqual(weekly["result"]["visibility"], "tenant")

                experience_status, experience = _request(
                    server.server_address[1],
                    "/api/reports/analysis-result/save-experience",
                    {"result_id": result["id"]},
                )
                self.assertEqual(experience_status, 200)
                self.assertEqual(experience["record"]["status"], "candidate")
                self.assertEqual(experience["record"]["subject_type"], "user")
                self.assertEqual(experience["record"]["subject_id"], "u_super_admin")
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
        bindings = json.dumps({"bindings": [{"token": "test-workbuddy-token", "channel": "workbuddy", "tenant_id": "tenant_demo", "user_id": "u_super_admin"}]})
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
