from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.platform.bootstrap import build_local_platform


class ReportRetentionTest(unittest.TestCase):
    def test_configured_retention_archives_old_results_and_versions_idempotently(self) -> None:
        services = build_local_platform()
        self.addCleanup(services.close)
        tenant_id = "tenant_demo"
        services.system_config_store.upsert_system_param(
            tenant_id,
            {"id": "report_retention_days", "name": "报告保留期限（天）", "value": "30", "category": "data", "description": "test"},
            "u_admin",
        )
        for suffix, saved_at in (("old", "2026-05-01T00:00:00+00:00"), ("new", "2026-07-05T00:00:00+00:00")):
            services.report_store.upsert_analysis_result(
                tenant_id,
                {
                    "id": f"result_{suffix}",
                    "title": suffix,
                    "analysisTaskId": f"task_{suffix}",
                    "savedAt": saved_at,
                },
                "u_admin",
            )
            services.report_store.save_weekly_report_version(
                tenant_id,
                {
                    "id": f"version_{suffix}",
                    "reportId": "weekly_report",
                    "name": suffix,
                    "savedAt": saved_at,
                    "report": {"id": "weekly_report", "title": suffix, "sections": []},
                },
                "u_admin",
            )
        result = services.report_retention_service.enforce(
            tenant_id,
            now=datetime(2026, 7, 10, tzinfo=timezone.utc),
        )
        self.assertEqual(result["archived"], {"analysis_results": 1, "weekly_versions": 1})
        self.assertEqual([item["id"] for item in services.report_store.list_analysis_results(tenant_id)], ["result_new"])
        self.assertEqual([item["id"] for item in services.report_store.list_weekly_report_versions(tenant_id)], ["version_new"])
        self.assertEqual(
            services.report_retention_service.enforce(
                tenant_id,
                now=datetime(2026, 7, 10, tzinfo=timezone.utc),
            )["archived"],
            {"analysis_results": 0, "weekly_versions": 0},
        )

    def test_sqlite_retention_is_durable_soft_archive_not_delete(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "platform.sqlite"
            services = build_local_platform(db_path)
            try:
                services.system_config_store.upsert_system_param(
                    "tenant_demo",
                    {"id": "report_retention_days", "name": "报告保留期限（天）", "value": "1", "category": "data", "description": "test"},
                    "u_admin",
                )
                services.report_store.upsert_analysis_result(
                    "tenant_demo",
                    {
                        "id": "old_result",
                        "title": "old",
                        "analysisTaskId": "task_old",
                        "savedAt": "2026-01-01T00:00:00+00:00",
                    },
                    "u_admin",
                )
                services.report_retention_service.enforce(
                    "tenant_demo", now=datetime(2026, 7, 10, tzinfo=timezone.utc)
                )
                row = services.report_store._conn.execute(
                    "SELECT archived_at FROM platform_saved_analysis_results WHERE tenant_id = ? AND result_id = ?",
                    ("tenant_demo", "old_result"),
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertTrue(row["archived_at"])
                self.assertEqual(services.report_store.list_analysis_results("tenant_demo"), [])
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
