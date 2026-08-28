from __future__ import annotations

import unittest

from backend.platform.api.routes.assets import _crawler_catalog_key, _merge_crawler_sql_catalog


class DataCrawlerCatalogProjectionTest(unittest.TestCase):
    def test_script_without_csv_is_visible_but_not_data_available(self) -> None:
        items = _merge_crawler_sql_catalog(
            [],
            [{
                "institutionId": "huaxing",
                "institutionName": "华兴银行",
                "sqlId": "sql_pending",
                "sqlName": "待执行日报",
                "parameters": [{"name": "today", "type": "date"}],
            }],
            institution_id="huaxing",
            institution_name="华兴银行",
        )

        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["dataAvailable"])
        self.assertEqual(items[0]["deliveryStatus"], "not_executed")
        self.assertEqual(items[0]["fields"], [])
        self.assertEqual(items[0]["previewRows"], [])
        self.assertNotIn("sourceKey", items[0])
        self.assertEqual(items[0]["catalogKey"], _crawler_catalog_key("huaxing", "sql_pending"))

    def test_manifest_backed_csv_attaches_to_the_same_sql_catalog_identity(self) -> None:
        table = {
            "id": "csv_delivery",
            "sourceKey": "stable-data-source",
            "sqlId": "sql_daily",
            "tableNameCn": "经营日报_2026-07-25",
            "fields": [{"fieldNameEn": "amount", "fieldNameCn": "金额", "type": "decimal"}],
            "previewRows": [{"金额": "100"}],
            "updatedAt": "2026-07-25T01:00:00+08:00",
        }
        items = _merge_crawler_sql_catalog(
            [table],
            [{
                "institutionId": "huaxing",
                "sqlId": "sql_daily",
                "sqlName": "经营日报",
                "parameters": [],
            }],
            institution_id="huaxing",
            institution_name="华兴银行",
        )

        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["dataAvailable"])
        self.assertEqual(items[0]["deliveryStatus"], "available")
        self.assertEqual(items[0]["sourceKey"], "stable-data-source")
        self.assertEqual(items[0]["updatedAt"], "2026-07-25T01:00:00+08:00")
        self.assertEqual(items[0]["catalogKey"], _crawler_catalog_key("huaxing", "sql_daily"))

    def test_foreign_institution_binding_never_enters_current_catalog(self) -> None:
        items = _merge_crawler_sql_catalog(
            [],
            [{"institutionId": "guangzhou", "sqlId": "sql_foreign", "sqlName": "广州日报"}],
            institution_id="huaxing",
            institution_name="华兴银行",
        )
        self.assertEqual(items, [])

    def test_latest_successful_delivery_wins_without_an_age_cutoff(self) -> None:
        tables = [
            {
                "id": "csv_july_01",
                "sourceKey": "daily-source",
                "sqlId": "sql_daily",
                "tableNameCn": "经营日报_2026-07-01",
                "crawlerFinishedAt": "2026-07-01T08:00:00+08:00",
                "updatedAt": "2026-07-01T08:00:00+08:00",
                "fields": [],
                "previewRows": [],
            },
            {
                "id": "csv_july_25",
                "sourceKey": "daily-source",
                "sqlId": "sql_daily",
                "tableNameCn": "经营日报_2026-07-25",
                "crawlerFinishedAt": "2026-07-25T08:00:00+08:00",
                "updatedAt": "2026-07-25T08:00:00+08:00",
                "fields": [],
                "previewRows": [],
            },
        ]
        items = _merge_crawler_sql_catalog(
            tables,
            [{"institutionId": "huaxing", "sqlId": "sql_daily", "sqlName": "经营日报"}],
            institution_id="huaxing",
            institution_name="华兴银行",
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "csv_july_25")
        self.assertTrue(items[0]["dataAvailable"])


if __name__ == "__main__":
    unittest.main()
