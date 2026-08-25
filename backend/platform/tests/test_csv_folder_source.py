from __future__ import annotations

import hashlib
import json
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
            self.assertEqual(len(table["sourceKey"]), 32)
            self.assertEqual(len(table["schemaFingerprint"]), 32)
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

    def test_tenant_catalog_uses_chinese_crawler_output_directory_not_english_institution_id(self) -> None:
        bindings = (
            ("tenant:华兴银行", "华兴银行", "huaxing"),
            ("tenant:南京银行", "南京银行", "nanjing"),
            ("tenant:广州银行", "广州银行", "guangzhou"),
            # Relational production tenants use canonical English codes, while
            # Data Crawler publishes into Chinese institution directories.
            ("tenant:huaxing", "华兴银行", "huaxing"),
            ("tenant:lanzhou", "兰州银行", "lanzhou"),
        )
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for tenant_id, directory, slug in bindings:
                expected = root / directory / "业务数据.csv"
                wrong = root / slug / "错误目录.csv"
                expected.parent.mkdir(parents=True, exist_ok=True)
                wrong.parent.mkdir(parents=True, exist_ok=True)
                expected.write_text(f"机构,金额\n{directory},1\n", encoding="utf-8")
                wrong.write_text("机构,金额\n错误目录,999\n", encoding="utf-8")

                source = CSVFolderSource(root).for_tenant(tenant_id)
                source.prime_catalog()

                with self.subTest(tenant_id=tenant_id):
                    self.assertEqual(source.root, (root / directory).resolve())
                    self.assertEqual([item["file_name"] for item in source.snapshot()["files"]], ["业务数据.csv"])
                    self.assertEqual(source.table_assets()[0]["previewRows"][0]["机构"], directory)

    def test_environment_uses_local_checkout_when_app_data_mount_is_empty(self) -> None:
        local_root = CSVFolderSource.local_data_crawler_root
        self.assertTrue(local_root.is_dir(), "local Data Crawler checkout must exist for this development test")
        with TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"SMART_DATA_AGENT_DATA_CRAWLER_ROOT": ""}, clear=False), patch.object(
            CSVFolderSource, "container_data_crawler_root", Path(tmpdir) / "empty-app-data"
        ):
            CSVFolderSource.container_data_crawler_root.mkdir()
            source = CSVFolderSource.from_environment()
        self.assertEqual(source.root, local_root.resolve())

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
            tables = source.table_assets()
            self.assertEqual([item["rowCount"] for item in tables], [1, 1, 1])
            self.assertEqual(
                [item["tableNameCn"] for item in tables],
                ["经营日报_2026-07-19", "经营明细_本月", "经营明细_近7天"],
            )

    def test_timestamped_deliveries_use_title_date_and_one_stable_source(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            delivery_dir = root / "csv" / "source_huaxing" / "2026-08-14"
            delivery_dir.mkdir(parents=True)
            first_path = delivery_dir / "20260814_105556_自营双周会每周新增余额放款.csv"
            latest_path = delivery_dir / "20260814_110040_自营双周会每周新增余额放款.csv"
            first_path.write_text("机构,金额\nA,1\n", encoding="utf-8")
            latest_path.write_text("机构,金额\nA,2\n", encoding="utf-8")
            os.utime(first_path, (1, 1))
            os.utime(latest_path, (2, 2))

            source = CSVFolderSource(root)
            snapshot = source.snapshot()
            table = source.table_assets()[0]

            self.assertEqual(snapshot["physical_file_count"], 2)
            self.assertEqual(snapshot["superseded_file_count"], 1)
            self.assertEqual(snapshot["file_count"], 1)
            self.assertEqual(table["tableNameCn"], "自营双周会每周新增余额放款_2026-08-14")
            self.assertEqual(table["fileName"], latest_path.name)
            self.assertEqual(table["relativePath"], "csv/source_huaxing/2026-08-14/20260814_110040_自营双周会每周新增余额放款.csv")
            self.assertEqual(table["previewRows"][0]["金额"], "2")

    def test_display_name_normalizes_leading_and_trailing_delivery_dates(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "20260814_双周报业务进度查询.csv").write_text("机构,金额\nA,1\n", encoding="utf-8")
            (root / "标品双周会周度sql_2026-05-06.csv").write_text("机构,金额\nA,2\n", encoding="utf-8")

            tables = CSVFolderSource(root).table_assets()

            self.assertEqual(
                [item["tableNameCn"] for item in tables],
                ["双周报业务进度查询_2026-08-14", "标品双周会周度sql_2026-05-06"],
            )

    def test_source_key_stays_stable_across_timestamped_delivery_dates(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first_dir = root / "csv" / "source_huaxing" / "2026-08-13"
            first_dir.mkdir(parents=True)
            first_path = first_dir / "20260813_090000_经营日报.csv"
            first_path.write_text("机构,金额\nA,1\n", encoding="utf-8")
            source = CSVFolderSource(root)
            first_table = source.table_assets()[0]

            latest_dir = root / "csv" / "source_huaxing" / "2026-08-14"
            latest_dir.mkdir(parents=True)
            latest_path = latest_dir / "20260814_090000_经营日报.csv"
            latest_path.write_text("机构,金额\nA,2\n", encoding="utf-8")
            latest_table = source.table_assets(force=True)[0]

            self.assertEqual(first_table["sourceKey"], latest_table["sourceKey"])
            self.assertEqual(latest_table["tableNameCn"], "经营日报_2026-08-14")
            self.assertEqual(latest_table["fileName"], latest_path.name)

    def test_catalog_excludes_data_crawler_operational_artifacts(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "业务数据.csv").write_text("机构,金额\nA,1\n", encoding="utf-8")
            (root / "metadata").mkdir()
            (root / "metadata" / "毓数_我的查询目录.csv").write_text("目录,SQL\ndefault,select 1\n", encoding="utf-8")
            (root / "系统验证").mkdir()
            (root / "系统验证" / "SQL 连通性验证.csv").write_text("crawler_health_check\n1\n", encoding="utf-8")
            (root / "采集链路健康检查_2026-08-11.csv").write_text("crawler_health_check\n1\n", encoding="utf-8")
            (root / "SQL 编辑器运行_2026-08-10.csv").write_text("机构,金额\nA,1\n", encoding="utf-8")

            source = CSVFolderSource(root)

            self.assertEqual([item["relative_path"] for item in source.snapshot()["files"]], ["业务数据.csv"])
            self.assertEqual([item["tableNameCn"] for item in source.table_assets()], ["业务数据"])

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

    def test_tenant_catalog_reads_only_source_id_folders_bound_by_crawler_metadata(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "metadata").mkdir()
            (root / "metadata" / "sources.json").write_text(json.dumps({
                "items": [
                    {"id": "source_huaxing", "institutionId": "huaxing"},
                    {"id": "source_zhengzhou", "institutionId": "zhengzhou"},
                ],
            }), encoding="utf-8")
            huaxing_path = root / "csv" / "source_huaxing" / "2026-08-14" / "20260814_100000_经营日报.csv"
            zhengzhou_path = root / "csv" / "source_zhengzhou" / "2026-08-14" / "20260814_100000_郑州日报.csv"
            huaxing_path.parent.mkdir(parents=True)
            zhengzhou_path.parent.mkdir(parents=True)
            huaxing_path.write_text("机构,金额\n华兴银行,1\n", encoding="utf-8")
            zhengzhou_path.write_text("机构,金额\n郑州银行,2\n", encoding="utf-8")

            tenant_source = CSVFolderSource(root).for_tenant("tenant:华兴银行")
            tenant_source.prime_catalog()

            self.assertEqual(
                [item["relative_path"] for item in tenant_source.snapshot()["files"]],
                ["csv/source_huaxing/2026-08-14/20260814_100000_经营日报.csv"],
            )
            self.assertEqual(tenant_source.table_assets()[0]["previewRows"][0]["机构"], "华兴银行")
            with self.assertRaises(FileNotFoundError):
                tenant_source.read("csv/source_zhengzhou/2026-08-14/20260814_100000_郑州日报.csv")

    def test_production_manifest_is_exact_tenant_and_file_boundary(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            institution = root / "华兴银行"
            institution.mkdir()
            approved = institution / "经营日报.csv"
            approved.write_text("机构,金额\n华兴银行,1\n", encoding="utf-8")
            # A stale file present on the mount is not part of the signed
            # delivery and therefore cannot enter the runtime catalog.
            (institution / "旧文件.csv").write_text("机构,金额\n华兴银行,999\n", encoding="utf-8")
            self._write_manifest(root, "tenant:华兴银行", "华兴银行", approved)

            with patch.dict(os.environ, {"SMART_DATA_AGENT_ENV": "production"}, clear=False):
                source = CSVFolderSource(root).for_tenant("tenant:华兴银行")
                snapshot = source.snapshot(force=True)

            self.assertEqual(snapshot["contract_status"], "validated")
            self.assertEqual(snapshot["contract_error"], "")
            self.assertEqual([item["file_name"] for item in snapshot["files"]], ["经营日报.csv"])
            self.assertEqual(snapshot["tenant_id"], "tenant:华兴银行")

    def test_production_manifest_missing_and_wrong_tenant_fail_closed(self) -> None:
        with TemporaryDirectory() as tmpdir, patch.dict(
            os.environ, {"SMART_DATA_AGENT_ENV": "production"}, clear=False
        ):
            root = Path(tmpdir)
            (root / "华兴银行").mkdir()
            (root / "华兴银行" / "经营日报.csv").write_text("机构,金额\nA,1\n", encoding="utf-8")
            missing = CSVFolderSource(root).for_tenant("tenant:华兴银行").snapshot(force=True)
            self.assertEqual(missing["contract_status"], "invalid")
            self.assertEqual(missing["contract_error"], "crawler_manifest_missing")
            self.assertEqual(missing["files"], [])

            approved = root / "华兴银行" / "经营日报.csv"
            self._write_manifest(root, "tenant:华兴银行", "华兴银行", approved)
            wrong = CSVFolderSource(root).for_tenant("tenant:郑州银行").snapshot(force=True)
            self.assertEqual(wrong["contract_status"], "invalid")
            self.assertEqual(wrong["contract_error"], "crawler_tenant_directory_mapping_missing")
            self.assertEqual(wrong["files"], [])

    def test_slug_directory_manifest_fails_closed_instead_of_overriding_chinese_crawler_directory(self) -> None:
        with TemporaryDirectory() as tmpdir, patch.dict(
            os.environ, {"SMART_DATA_AGENT_ENV": "production"}, clear=False
        ):
            root = Path(tmpdir)
            chinese = root / "华兴银行" / "经营日报.csv"
            legacy = root / "huaxing" / "经营日报.csv"
            chinese.parent.mkdir()
            legacy.parent.mkdir()
            chinese.write_text("机构,金额\n华兴银行,1\n", encoding="utf-8")
            legacy.write_text("机构,金额\n错误目录,999\n", encoding="utf-8")
            self._write_manifest(root, "tenant:华兴银行", "huaxing", legacy)

            source = CSVFolderSource(root).for_tenant("tenant:华兴银行")
            snapshot = source.snapshot(force=True)

            self.assertEqual(snapshot["contract_status"], "invalid")
            self.assertEqual(snapshot["contract_error"], "crawler_tenant_directory_mismatch")
            self.assertEqual(snapshot["files"], [])
            self.assertNotEqual(source.root, legacy.parent.resolve())

    def test_production_manifest_checksum_mismatch_fails_closed(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            institution = root / "华兴银行"
            institution.mkdir()
            approved = institution / "经营日报.csv"
            approved.write_text("机构,金额\n华兴银行,1\n", encoding="utf-8")
            self._write_manifest(root, "tenant:华兴银行", "华兴银行", approved)
            approved.write_text("机构,金额\n华兴银行,2\n", encoding="utf-8")

            with patch.dict(os.environ, {"SMART_DATA_AGENT_ENV": "production"}, clear=False):
                snapshot = CSVFolderSource(root).for_tenant("tenant:华兴银行").snapshot(force=True)

            self.assertEqual(snapshot["contract_status"], "invalid")
            self.assertEqual(snapshot["contract_error"], "crawler_manifest_file_checksum_mismatch")
            self.assertEqual(snapshot["files"], [])

    @staticmethod
    def _write_manifest(root: Path, tenant_id: str, directory: str, file_path: Path) -> None:
        content = file_path.read_bytes()
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "smart-data-crawler-manifest/v1",
                    "generated_at": "2026-08-22T00:00:00+00:00",
                    "tenants": [
                        {
                            "tenant_id": tenant_id,
                            "institution_directory": directory,
                            "schema_version": "crawler-tenant/v1",
                            "files": [
                                {
                                    "path": file_path.relative_to(root / directory).as_posix(),
                                    "sha256": hashlib.sha256(content).hexdigest(),
                                }
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
