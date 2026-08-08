from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.platform.ingestion.topic_data import TopicDataStore


def _task(task_id: str, amount: int) -> dict:
    return {
        "task_id": task_id,
        "execution_id": task_id,
        "question": "测试分析",
        "status": "completed",
        "skill_results": [{"data": [{"branch_name": "测试分行", "loan_amount": amount}], "sql": "SELECT 1"}],
    }


class TopicDataStoreTest(unittest.TestCase):
    def test_history_shortcut_and_topic_use_current_snapshot_only(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = TopicDataStore(Path(tmpdir) / "Topic_Data")
            references = store.record_analysis_execution(
                tenant_id="tenant_a",
                user_id="user_a",
                task=_task("task_a", 10),
                source_reference={"type": "shortcut", "id": "shortcut_a"},
            )
            self.assertEqual(references["history"]["folder"], "analysis/tenant_a/user_a/history/task_a")
            self.assertEqual(references["shortcut"]["folder"], "analysis/tenant_a/user_a/shortcuts/shortcut_a")
            shortcut = store.read_reference(
                tenant_id="tenant_a", user_id="user_a", reference_type="shortcut", reference_id="shortcut_a"
            )
            self.assertEqual(shortcut["rows"][0]["loan_amount"], "10")

            store.record_topic_table_result(
                tenant_id="tenant_a", user_id="user_a", topic_table_id="topic_a", sql="SELECT 1", rows=[{"amount": 1}]
            )
            store.record_topic_table_result(
                tenant_id="tenant_a", user_id="user_a", topic_table_id="topic_a", sql="SELECT 2", rows=[{"amount": 2}]
            )
            topic = store.read_reference(
                tenant_id="tenant_a", user_id="user_a", reference_type="topic", reference_id="topic_a"
            )
            self.assertEqual(topic["folder"], "tenant_a/topics/topic_a/current")
            self.assertEqual(topic["rows"], [{"amount": "2"}])
            self.assertEqual(topic["manifest"]["version_id"], "current")
            self.assertFalse((Path(tmpdir) / "Topic_Data" / "tenant_a" / "topics" / "topic_a" / "versions").exists())
            index = json.loads((Path(tmpdir) / "Topic_Data" / "tenant_a" / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["entries"]["tenant_a:user_a:topic:topic_a"]["version_count"], 1)

    def test_saved_report_migration_uses_one_current_snapshot(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "Topic_Data"
            store = TopicDataStore(root)
            first = store.record_saved_report_snapshot(
                tenant_id="tenant_a",
                user_id="user_a",
                report_id="report_a",
                report={"title": "历史报告", "rows": [{"机构": "A", "金额": 10}]},
            )
            second = store.record_saved_report_snapshot(
                tenant_id="tenant_a",
                user_id="user_a",
                report_id="report_a",
                report={"title": "历史报告", "rows": [{"机构": "B", "金额": 20}]},
            )
            self.assertEqual(first["folder"], "reports/tenant_a/report_a/current")
            self.assertEqual(second["folder"], first["folder"])
            snapshot = store.read_reference(
                tenant_id="tenant_a", user_id="user_a", reference_type="report", reference_id="report_a"
            )
            self.assertEqual(snapshot["rows"], [{"机构": "B", "金额": "20"}])
            self.assertFalse((root / "reports" / "tenant_a" / "report_a" / "versions").exists())
