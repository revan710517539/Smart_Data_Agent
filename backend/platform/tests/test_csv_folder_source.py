from __future__ import annotations

import hashlib
import os
import unittest
from time import perf_counter
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.platform.ingestion.csv_folder import CSVFolderSource


class CSVFolderSourceTest(unittest.TestCase):
    def test_snapshot_and_read_use_configured_csv_folder(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            csv_path = root / "智能运营" / "sample.csv"
            csv_path.parent.mkdir()
            content = "\ufeff机构,说明\n华兴银行,\"第一行\n第二行\"\n".encode("utf-8")
            csv_path.write_bytes(content)

            source = CSVFolderSource(root)
            snapshot = source.snapshot()

            self.assertTrue(snapshot["available"])
            self.assertTrue(snapshot["source_read_only"])
            self.assertEqual(snapshot["file_count"], 1)
            self.assertEqual(snapshot["files"][0]["relative_path"], "智能运营/sample.csv")
            self.assertEqual(snapshot["files"][0]["row_count"], 1)
            self.assertEqual(snapshot["files"][0]["columns"], ["机构", "说明"])
            self.assertEqual(snapshot["files"][0]["content_hash"], hashlib.sha256(content).hexdigest())
            self.assertEqual(source.read("智能运营/sample.csv"), content)
            table = source.table_assets()[0]
            self.assertEqual(table["tableNameCn"], "sample")
            self.assertEqual(table["relativePath"], "智能运营/sample.csv")
            self.assertEqual(table["rowCount"], 1)
            self.assertEqual(table["previewRows"], [{"机构": "华兴银行", "说明": "第一行\n第二行"}])
            self.assertEqual(table["fields"][0]["fieldNameCn"], "机构")
            with self.assertRaises(PermissionError):
                source.read("../outside.csv")

    def test_environment_prefers_explicit_deployed_data_crawler_root(self) -> None:
        with TemporaryDirectory() as tmpdir:
            deployed_root = Path(tmpdir) / "crawler-csv"
            with patch.dict(os.environ, {"SMART_DATA_AGENT_DATA_CRAWLER_ROOT": str(deployed_root)}):
                source = CSVFolderSource.from_environment()
            self.assertEqual(source.root, deployed_root.resolve())
            # A missing configured mount cannot fall back to either the local
            # crawler checkout or legacy Origin_Data.
            self.assertFalse(source.snapshot()["available"])
            self.assertEqual(source.for_tenant("tenant_a").snapshot()["files"], [])

    def test_environment_uses_local_data_crawler_root_when_present(self) -> None:
        local_root = CSVFolderSource.local_data_crawler_root
        self.assertTrue(local_root.is_dir(), "local Data Crawler checkout must exist for this development test")
        with TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"SMART_DATA_AGENT_DATA_CRAWLER_ROOT": ""}, clear=False), patch.object(
            CSVFolderSource, "container_data_crawler_root", Path(tmpdir) / "missing-app-data"
        ):
            source = CSVFolderSource.from_environment()
        self.assertEqual(source.root, local_root.resolve())

    def test_environment_uses_app_data_mount_before_local_checkout(self) -> None:
        with TemporaryDirectory() as tmpdir:
            app_data = Path(tmpdir) / "app-data"
            (app_data / "华兴银行").mkdir(parents=True)
            (app_data / "华兴银行" / "loan.csv").write_text("机构,金额\n华兴银行,1\n", encoding="utf-8")
            with patch.dict(os.environ, {"SMART_DATA_AGENT_DATA_CRAWLER_ROOT": ""}, clear=False), patch.object(
                CSVFolderSource, "container_data_crawler_root", app_data
            ):
                source = CSVFolderSource.from_environment()
            tenant_source = source.for_tenant("tenant:华兴银行")
            tenant_source.prime_catalog()
            self.assertEqual(source.root, app_data.resolve())
            self.assertEqual([item["file_name"] for item in tenant_source.snapshot()["files"]], ["loan.csv"])

    def test_daily_delivery_versions_expose_only_the_latest_source_file(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "daily").mkdir()
            (root / "daily" / "经营日报2026-07-18.csv").write_text("机构,金额\nA,10\n", encoding="utf-8")
            (root / "daily" / "经营日报2026-07-19.csv").write_text("机构,金额\nA,20\n", encoding="utf-8")
            # Different time windows are distinct current sources, not
            # delivery versions of one another.
            (root / "daily" / "经营明细_近7天.csv").write_text("机构,金额\nA,1\n", encoding="utf-8")
            (root / "daily" / "经营明细_本月.csv").write_text("机构,金额\nA,2\n", encoding="utf-8")
            source = CSVFolderSource(root)
            snapshot = source.snapshot()
            self.assertEqual(snapshot["physical_file_count"], 4)
            self.assertEqual(snapshot["superseded_file_count"], 1)
            self.assertEqual(snapshot["file_count"], 3)
            self.assertEqual(
                [item["relative_path"] for item in snapshot["files"]],
                ["daily/经营日报2026-07-19.csv", "daily/经营明细_本月.csv", "daily/经营明细_近7天.csv"],
            )
            self.assertEqual([item["rowCount"] for item in source.table_assets()], [1, 1, 1])

    def test_catalog_reuses_cached_snapshot_and_table_assets_until_forced_refresh(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "daily.csv"
            source_path.write_text("机构,金额\nA,1\n", encoding="utf-8")
            source = CSVFolderSource(root)
            source.prime_catalog()
            source_path.write_text("机构,金额\nA,2\n", encoding="utf-8")
            # Interactive reads retain the coherent primed catalog until the
            # bounded cache window expires or the batch forces a refresh.
            self.assertEqual(source.table_assets()[0]["previewRows"][0]["金额"], "1")
            self.assertEqual(source.table_assets(force=True)[0]["previewRows"][0]["金额"], "2")

    def test_tenant_catalog_never_falls_back_to_another_institution(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "tenant_a").mkdir()
            (root / "tenant_b").mkdir()
            (root / "tenant_a" / "a.csv").write_text("机构,金额\nA,1\n", encoding="utf-8")
            (root / "tenant_b" / "b.csv").write_text("机构,金额\nB,2\n", encoding="utf-8")
            source = CSVFolderSource(root)
            a_source = source.for_tenant("tenant_a")
            a_source.prime_catalog()
            self.assertEqual([item["file_name"] for item in a_source.snapshot()["files"]], ["a.csv"])
            missing_source = source.for_tenant("tenant_missing")
            missing_source.prime_catalog()
            self.assertEqual(missing_source.snapshot()["files"], [])
