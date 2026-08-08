from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from backend.platform.automation.store import _next_run

from backend.platform.assets import InMemoryDataAssetStore
from backend.platform.ingestion.csv_folder import CSVFolderSource
from backend.platform.ingestion.topic_batch import TopicDataBatchService
from backend.platform.ingestion.topic_data import TopicDataStore


class TopicDataBatchServiceTest(unittest.TestCase):
    def test_daily_schedule_uses_shanghai_timezone_without_croniter(self) -> None:
        self.assertEqual(
            _next_run("0 2 * * *", "2026-07-31T13:00:00+00:00", "Asia/Shanghai"),
            "2026-07-31T18:00:00+00:00",
        )

    def test_batch_reads_origin_csv_and_overwrites_current_topic_data(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "tenant_a").mkdir()
            (root / "tenant_a" / "loan.csv").write_text(
                "tenant_id,branch_name,product_line,customer_segment,month,drawdown_amount,loan_balance,m1_overdue_balance\n"
                "*,A,经营贷,小微,2026-07,20,100,4\n"
                "*,B,消费贷,个人,2026-07,10,50,1\n",
                encoding="utf-8",
            )
            assets = InMemoryDataAssetStore(seed_defaults=False)
            topic = assets.upsert_item(
                "tenant_a",
                "topic_table",
                {
                    "id": "topic_a",
                    "name": "分行放款",
                    "code": "branch_loan",
                    "description": "测试",
                    "sql": "SELECT branch_name, SUM(loan_amount) AS loan_amount FROM loan_operation_fact WHERE tenant_id = :tenant_id GROUP BY branch_name ORDER BY branch_name",
                    "fields": [
                        {"fieldNameEn": "branch_name", "fieldNameCn": "机构", "type": "string", "explanation": "机构"},
                        {"fieldNameEn": "loan_amount", "fieldNameCn": "放款金额", "type": "decimal", "explanation": "放款金额"},
                    ],
                },
                updated_by="reviewer",
                lifecycle_status="active",
            )
            self.assertEqual(topic["lifecycleStatus"], "active")
            store = TopicDataStore(root / "Topic_Data")
            batch = TopicDataBatchService(CSVFolderSource(root), store, assets)
            outcome = batch.run("tenant_a", "user_a")
            self.assertEqual(outcome["succeeded"], 1)
            snapshot = store.read_reference(
                tenant_id="tenant_a", user_id="user_a", reference_type="topic", reference_id="topic_a"
            )
            self.assertEqual(snapshot["rows"], [{"branch_name": "A", "loan_amount": "20"}, {"branch_name": "B", "loan_amount": "10"}])

    def test_missing_source_table_is_explicit_failure(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "tenant_a").mkdir()
            (root / "tenant_a" / "minimal.csv").write_text("tenant_id,value\n*,1\n", encoding="utf-8")
            assets = InMemoryDataAssetStore(seed_defaults=False)
            assets.upsert_item(
                "tenant_a", "topic_table",
                {
                    "id": "topic_a", "name": "缺失源", "code": "missing", "description": "测试",
                    "sql": "SELECT * FROM missing_fact WHERE tenant_id = :tenant_id",
                    "fields": [{"fieldNameEn": "value", "fieldNameCn": "值", "type": "decimal", "explanation": "值"}],
                },
                updated_by="reviewer", lifecycle_status="active",
            )
            outcome = TopicDataBatchService(CSVFolderSource(root), TopicDataStore(root / "Topic_Data"), assets).run("tenant_a", "user_a")
            self.assertEqual(outcome["topic_tables"][0]["error_code"], "origin_data_table_not_found")

    def test_voice_origin_csv_supports_customer_and_channel_legacy_topics(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "tenant_a").mkdir()
            (root / "tenant_a" / "voice.csv").write_text(
                "tenant_id,branch_name,product_line,month,channel,customer_segment,loan_amount,drawdown_rate,drawdown_amount,eligible_amount\n"
                "*,上海分行,经营贷,2026-07,客户经理,小微,100,0.5,50,200\n",
                encoding="utf-8",
            )
            assets = InMemoryDataAssetStore(seed_defaults=False)
            for item_id, name, sql, fields in (
                (
                    "topic_customer", "客群", "SELECT customer_segment, conversion_rate FROM customer_operation_mart WHERE tenant_id = :tenant_id",
                    [{"fieldNameEn": "customer_segment", "fieldNameCn": "客群", "type": "string", "explanation": "客群"}, {"fieldNameEn": "conversion_rate", "fieldNameCn": "转化率", "type": "decimal", "explanation": "转化率"}],
                ),
                (
                    "topic_channel", "渠道", "SELECT channel, roi FROM channel_operation_mart WHERE tenant_id = :tenant_id",
                    [{"fieldNameEn": "channel", "fieldNameCn": "渠道", "type": "string", "explanation": "渠道"}, {"fieldNameEn": "roi", "fieldNameCn": "ROI", "type": "decimal", "explanation": "ROI"}],
                ),
            ):
                assets.upsert_item(
                    "tenant_a", "topic_table",
                    {"id": item_id, "name": name, "code": item_id, "description": "测试", "sql": sql, "fields": fields},
                    updated_by="reviewer", lifecycle_status="active",
                )
            outcome = TopicDataBatchService(CSVFolderSource(root), TopicDataStore(root / "Topic_Data"), assets).run("tenant_a", "user_a")
            self.assertEqual(outcome["succeeded"], 2)
