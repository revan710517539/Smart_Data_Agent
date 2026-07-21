from __future__ import annotations

import unittest

from backend.platform.crawler_engine.systems.qifu_yushu.query_sync import (
    YUSHU_MY_QUERIES_PROFILE_ID,
    _raw_table_asset,
)


class YushuQuerySyncTests(unittest.TestCase):
    def test_raw_table_asset_keeps_folder_sql_identity_and_query_metadata(self) -> None:
        item = _raw_table_asset(
            query={
                "folderId": "612",
                "folderName": "周报",
                "queryId": "4239",
                "queryName": "华兴底表",
                "sql": "SELECT stat_date AS `统计日期`, SUM(loan_amt) AS `放款金额` FROM demo.loan_fact",
                "queryEngine": "Hive",
                "dataCenter": "BJMD",
                "dataSource": "Hive",
            },
            connection={"id": "data_yushu"},
        )

        self.assertEqual(item["id"], "raw_yushu_sql_4239")
        self.assertEqual(item["tableNameCn"], "周报-华兴底表")
        self.assertEqual(item["sourcePlatform"], "毓数")
        self.assertEqual(item["crawlerProfileId"], YUSHU_MY_QUERIES_PROFILE_ID)
        self.assertEqual(item["connectionId"], "data_yushu")
        self.assertEqual(item["sourceTables"], ["demo.loan_fact"])
        self.assertEqual([field["fieldNameCn"] for field in item["fields"]], ["统计日期", "放款金额"])
        self.assertTrue(item["fields"][0]["isTime"])
        self.assertTrue(item["fields"][1]["isMetric"])
        self.assertIn("不执行 SQL", item["restrictions"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
