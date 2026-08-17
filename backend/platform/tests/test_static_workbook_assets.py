from __future__ import annotations

import io
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from openpyxl import Workbook

from backend.platform.assets import InMemoryDataAssetStore
from backend.platform.ingestion import DataAcquisitionService, InMemoryAcquisitionStore
from backend.platform.ingestion.artifacts import LocalArtifactObjectStore


def _workbook_bytes() -> bytes:
    workbook = Workbook()
    first = workbook.active
    first.title = "放款数据"
    first.append(["日期", "放款金额"])
    first.append(["2026-08-01", 100])
    second = workbook.create_sheet("风险数据")
    second.append(["客户号", "风险等级"])
    second.append(["C001", "低"])
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


class StaticWorkbookAssetTest(unittest.TestCase):
    def test_each_non_empty_sheet_becomes_one_immutable_raw_table(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            crawler_root = root / "crawler"
            (crawler_root / "tenant_demo").mkdir(parents=True)
            assets = InMemoryDataAssetStore(seed_defaults=False)
            acquisition = InMemoryAcquisitionStore()
            object_store = LocalArtifactObjectStore(root / "objects")
            with patch.dict(os.environ, {"SMART_DATA_AGENT_DATA_CRAWLER_ROOT": str(crawler_root)}, clear=False):
                service = DataAcquisitionService(
                    acquisition,
                    object_store,
                    SimpleNamespace(),
                    data_asset_store=assets,
                )
            try:
                content = _workbook_bytes()
                uploaded = service.upload_raw_asset_file("tenant_demo", "飞书导出.xlsx", content, "u_admin")
                self.assertTrue(uploaded["immutable"])
                self.assertFalse(uploaded["duplicate"])
                self.assertEqual(uploaded["table_count"], 2)

                catalog = service.csv_source.for_tenant("tenant_demo").table_assets()
                static_tables = [item for item in catalog if item.get("sourcePlatform") == "静态工作簿"]
                self.assertEqual([item["sheetName"] for item in static_tables], ["放款数据", "风险数据"])
                self.assertTrue(all(str(item["relativePath"]).startswith("static://") for item in static_tables))
                headers, rows = service.csv_source.for_tenant("tenant_demo").read_rows(static_tables[0]["relativePath"])
                self.assertEqual(headers, ["日期", "放款金额"])
                self.assertEqual(rows, [{"日期": "2026-08-01", "放款金额": "100"}])

                duplicate = service.upload_raw_asset_file("tenant_demo", "飞书导出.xlsx", content, "u_admin")
                self.assertTrue(duplicate["duplicate"])
                self.assertEqual(duplicate["table_count"], 2)
                self.assertEqual(len([
                    item for item in assets.list_bundle("tenant_demo")["raw_tables"]
                    if item.get("staticWorkbookVersion") == 1
                ]), 1)
            finally:
                service.close()
                acquisition.close()


if __name__ == "__main__":
    unittest.main()
