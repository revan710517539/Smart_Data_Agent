from __future__ import annotations

import hashlib
import os
import unittest
from time import perf_counter
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.platform.bootstrap import build_local_platform
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

    def test_platform_uses_project_csv_catalog_without_external_collection_runtime(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "platform.sqlite"
            ignored_external_root = Path(tmpdir) / "external-csv"
            ignored_external_root.mkdir()
            (ignored_external_root / "outside.csv").write_text("outside\n1\n", encoding="utf-8")
            with patch.dict(os.environ, {"SMART_DATA_AGENT_CSV_SOURCE_ROOT": str(ignored_external_root)}):
                services = build_local_platform(db_path)
                try:
                    source = services.data_acquisition_service.csv_source
                    project_root = Path(__file__).resolve().parents[3] / "Origin_Data"
                    physical_file_count = len(list(project_root.rglob("*.csv")))
                    self.assertEqual(source.root, project_root.resolve())
                    snapshot = source.snapshot()
                    expected_count = snapshot["file_count"]
                    self.assertEqual(snapshot["physical_file_count"], physical_file_count)
                    self.assertGreater(expected_count, 0)
                    self.assertLessEqual(expected_count, physical_file_count)
                    self.assertEqual(len(source.table_assets()), expected_count)
                    self.assertNotIn("outside", [item["relativePath"] for item in source.table_assets()])
                    self.assertEqual(services.topic_metadata_service.__class__.__name__, "CSVTopicMetadataService")
                finally:
                    services.close()

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
