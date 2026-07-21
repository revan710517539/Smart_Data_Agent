from __future__ import annotations

import http.client
import json
import threading
import unittest
from tempfile import TemporaryDirectory

from backend.platform.api.server import create_server
from backend.platform.bootstrap import build_local_platform
from backend.platform.reports import WeeklyReportLearningEngine
from backend.platform.reports.store import CommentRevisionConflict


def _version(version_id: str = "weekly_v1", *, verified: bool = False) -> dict:
    evidence_ref = {
        "verified": True,
        "evidence_id": "ev_123",
        "evidence_hash": "a" * 64,
        "source_snapshot": {"snapshot_id": "p1", "observed_at": "2026-07-10T02:00:00Z"},
    } if verified else {}
    return {
        "id": version_id,
        "name": "上海分行经营周报",
        "savedAt": "2026/07/10 10:00",
        "reportId": "shanghai",
        "report": {
            "id": "shanghai",
            "institutionName": "上海分行",
            "period": "2026-07-06 ~ 2026-07-10",
            "sections": [
                {
                    "id": "performance",
                    "name": "业绩与业务波动",
                    "blocks": [
                        {
                            "id": "balance",
                            "type": "table",
                            "title": "余额达成情况",
                            "dataSource": "loan_operation_mart",
                            "fields": ["机构", "余额"],
                            "rows": [{"机构": "上海分行", "余额": 100}],
                            "evidenceRef": evidence_ref,
                            "analysis": {"status": "待确认", "conclusion": "余额稳定。"},
                        }
                    ],
                }
            ],
        },
        "comments": [],
    }


class ReportIntegrityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.services = build_local_platform()

    def tearDown(self) -> None:
        self.services.close()

    def test_weekly_versions_are_immutable_deduplicated_and_evidence_gated(self) -> None:
        unverified = self.services.report_store.save_weekly_report_version(
            "tenant_demo", _version(), updated_by="u_admin"
        )
        self.assertEqual(unverified["publicationStatus"], "review_required")
        self.assertEqual(unverified["evidenceSummary"]["unverified_block_ids"], ["balance"])
        idempotent = self.services.report_store.save_weekly_report_version(
            "tenant_demo", _version(), updated_by="u_admin"
        )
        self.assertEqual(idempotent["id"], unverified["id"])
        with self.assertRaises(ValueError):
            changed = _version()
            changed["report"]["sections"][0]["blocks"][0]["rows"][0]["余额"] = 999
            self.services.report_store.save_weekly_report_version(
                "tenant_demo", changed, updated_by="u_admin"
            )
        duplicate = self.services.report_store.save_weekly_report_version(
            "tenant_demo", _version("weekly_duplicate"), updated_by="u_admin"
        )
        self.assertTrue(duplicate["deduplicated"])
        self.assertEqual(duplicate["id"], "weekly_v1")

        verified = self.services.report_store.save_weekly_report_version(
            "tenant_demo", _version("weekly_verified", verified=True), updated_by="u_admin"
        )
        self.assertEqual(verified["publicationStatus"], "ready")
        self.assertEqual(verified["revisionNo"], 2)

    def test_comment_revisions_use_optimistic_concurrency_and_keep_history(self) -> None:
        first = [{"id": "c1", "targetId": "p1", "text": "第一次评论", "status": "open"}]
        self.services.report_store.replace_report_comments(
            "tenant_demo", "shanghai", first, updated_by="u_admin", expected_revision=0
        )
        self.assertEqual(self.services.report_store.get_comment_revision("tenant_demo", "shanghai"), 1)
        with self.assertRaises(CommentRevisionConflict) as raised:
            self.services.report_store.replace_report_comments(
                "tenant_demo", "shanghai", [], updated_by="u_reviewer", expected_revision=0
            )
        self.assertEqual(raised.exception.current_revision, 1)
        self.assertEqual(self.services.report_store.get_report_comments("tenant_demo", "shanghai")[0]["text"], "第一次评论")

    def test_comment_entities_are_server_authored_idempotent_and_mutated_one_at_a_time(self) -> None:
        with TemporaryDirectory() as tmpdir:
            services = build_local_platform(f"{tmpdir}/comments.sqlite")
            try:
                created = services.report_store.create_report_comment(
                    "tenant_demo",
                    "shanghai",
                    {
                        "id": "client-forged-id",
                        "targetId": "block_1_data",
                        "targetLabel": "余额表格",
                        "targetKind": "table",
                        "text": "请复核余额口径",
                        "author": "spoofed-user",
                        "time": "1999-01-01",
                        "status": "resolved",
                    },
                    "u_admin",
                    0,
                    "create-request-1",
                )
                comment = created["comment"]
                self.assertNotEqual(comment["id"], "client-forged-id")
                self.assertEqual(comment["author"], "平台管理员")
                self.assertEqual(comment["status"], "open")
                self.assertNotEqual(comment["time"], "1999-01-01")
                replay = services.report_store.create_report_comment(
                    "tenant_demo",
                    "shanghai",
                    {"targetId": "ignored", "targetLabel": "ignored", "text": "ignored"},
                    "u_admin",
                    1,
                    "create-request-1",
                )
                self.assertTrue(replay["idempotent_replay"])
                self.assertEqual(replay["revision"], 1)
                replied = services.report_store.mutate_report_comment(
                    "tenant_demo",
                    "shanghai",
                    comment["id"],
                    "reply",
                    {"text": "已核对真实数据源", "author": "spoofed-reviewer"},
                    "u_reviewer",
                    1,
                    "reply-request-1",
                )
                self.assertEqual(replied["comment"]["replies"][0]["author"], "平台复核员")
                resolved = services.report_store.mutate_report_comment(
                    "tenant_demo",
                    "shanghai",
                    comment["id"],
                    "resolve",
                    {"reason": "manual", "resolvedBy": "spoofed-user"},
                    "u_reviewer",
                    2,
                )
                self.assertEqual(resolved["comment"]["resolvedBy"], "u_reviewer")
                self.assertEqual(resolved["revision"], 3)
                with self.assertRaises(CommentRevisionConflict):
                    services.report_store.mutate_report_comment(
                        "tenant_demo", "shanghai", comment["id"], "reopen", {}, "u_admin", 2
                    )
                with self.assertRaises(PermissionError):
                    services.report_store.mutate_report_comment(
                        "tenant_demo", "shanghai", comment["id"], "delete", {}, "u_reviewer", 3
                    )
            finally:
                services.close()

    def test_weekly_learning_only_creates_review_candidates(self) -> None:
        version = self.services.report_store.save_weekly_report_version(
            "tenant_demo", _version(), updated_by="u_admin"
        )
        task = WeeklyReportLearningEngine(
            self.services.report_store,
            self.services.data_asset_store,
            self.services.application_store,
        ).analyze_version("tenant_demo", version["id"], "u_admin", force=True)
        self.assertEqual(task["status"], "已完成")
        candidates = self.services.report_store.list_learning_candidates("tenant_demo")
        self.assertTrue(candidates)
        self.assertTrue(all(item["status"] == "candidate" for item in candidates))
        self.assertFalse(
            [
                item for item in self.services.data_asset_store.list_bundle("tenant_demo")["analysis_experiences"]
                if item.get("sourceVersionId") == version["id"]
            ]
        )

    def test_http_learning_review_applies_candidate_only_for_second_reviewer(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/platform.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                saved = _request(
                    port,
                    "POST",
                    "/api/reports/weekly-version",
                    {"version": _version("weekly_http"), "analyze": True},
                    "u_admin",
                )
                self.assertEqual(saved[0], 200)
                learning = _request(
                    port,
                    "GET",
                    "/api/reports/weekly-learning",
                    None,
                    "u_admin",
                )
                candidates = learning[1]["learning_candidates"]
                method = next(item for item in candidates if item["candidate_type"] == "analysis_method")
                denied = _request(
                    port,
                    "POST",
                    "/api/reports/weekly-learning/review",
                    {"learning_candidate_id": method["learning_candidate_id"], "decision": "approve"},
                    "u_admin",
                )
                self.assertEqual(denied[0], 403)
                approved = _request(
                    port,
                    "POST",
                    "/api/reports/weekly-learning/review",
                    {"learning_candidate_id": method["learning_candidate_id"], "decision": "approve"},
                    "u_reviewer",
                )
                self.assertEqual(approved[0], 200)
                self.assertEqual(approved[1]["learning_candidate"]["status"], "applied")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


def _request(
    port: int,
    method: str,
    path: str,
    body: dict | None,
    user_id: str,
) -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"X-User-Id": user_id, "X-Tenant-Id": "tenant_demo"}
    encoded = None
    if body is not None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    connection.request(method, path, body=encoded, headers=headers)
    response = connection.getresponse()
    payload = json.loads(response.read().decode("utf-8"))
    connection.close()
    return response.status, payload


if __name__ == "__main__":
    unittest.main()
