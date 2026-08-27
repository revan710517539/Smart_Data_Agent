from __future__ import annotations

import unittest

from backend.platform.assets.store import InMemoryDataAssetStore
from backend.platform.memory.fusion import memory_identity, prepare_asset_fusion
from backend.platform.memory.models import MemoryRecord
from backend.platform.memory.store import InMemoryMemoryStore


class MemoryFusionTest(unittest.TestCase):
    def test_analysis_experience_same_topic_and_action_updates_latest_record(self) -> None:
        store = InMemoryDataAssetStore(seed_defaults=False)
        first = store.upsert_item(
            "tenant_a",
            "analysis_experience",
            {
                "id": "exp_old",
                "title": "在贷余额趋势分析",
                "steps": "旧分析过程",
                "sourceVersionId": "task_old",
                "evidence": "analysis_task:task_old",
                "updatedAt": "2026/8/20 10:00:00",
            },
            updated_by="author_a",
        )
        second = store.upsert_item(
            "tenant_a",
            "analysis_experience",
            {
                "id": "exp_new",
                "title": "给我一下在贷余额的趋势图",
                "steps": "最新分析过程",
                "sourceVersionId": "task_new",
                "evidence": "analysis_task:task_new",
                "updatedAt": "2026/8/22 10:00:00",
            },
            updated_by="author_a",
        )

        self.assertEqual(second["id"], first["id"])
        self.assertEqual(second["steps"], "最新分析过程")
        self.assertEqual(second["occurrenceCount"], 2)
        self.assertEqual(second["sourceVersionIds"], ["task_old", "task_new"])
        self.assertEqual(len(store.list_bundle("tenant_a")["analysis_experiences"]), 1)

    def test_same_topic_but_new_action_creates_a_separate_memory(self) -> None:
        store = InMemoryDataAssetStore(seed_defaults=False)
        common = {
            "memoryTopic": "在贷余额",
            "steps": "基于真实数据分析",
            "sourceVersionId": "task_1",
            "evidence": "analysis_task:task_1",
            "updatedAt": "2026-08-22T10:00:00+00:00",
        }
        store.upsert_item(
            "tenant_a",
            "analysis_experience",
            {**common, "id": "exp_trend", "title": "在贷余额趋势", "memoryAction": "trend"},
            updated_by="author_a",
        )
        store.upsert_item(
            "tenant_a",
            "analysis_experience",
            {**common, "id": "exp_reason", "title": "在贷余额原因", "memoryAction": "attribution"},
            updated_by="author_a",
        )
        self.assertEqual(len(store.list_bundle("tenant_a")["analysis_experiences"]), 2)

    def test_existing_consolidation_does_not_count_latest_payload_twice(self) -> None:
        existing = [
            {
                "id": "exp_old",
                "title": "在贷余额趋势分析",
                "steps": "旧分析过程",
                "updatedAt": "2026/8/20 10:00:00",
            },
            {
                "id": "exp_latest",
                "title": "给我一下在贷余额的趋势图",
                "steps": "最新分析过程",
                "updatedAt": "2026/8/22 10:00:00",
            },
        ]
        fusion = prepare_asset_fusion(
            "analysis_experience",
            dict(existing[-1]),
            existing,
            consolidate_existing=True,
        )
        self.assertEqual(fusion.item["occurrenceCount"], 2)
        self.assertEqual(fusion.item["steps"], "最新分析过程")

    def test_behavior_habit_identity_uses_action_and_target_type(self) -> None:
        first = memory_identity(
            "behavior_habit",
            {"action": "application.set_page_data_layout", "target_type": "application_module"},
            title="操作习惯：设置布局",
        )
        repeated = memory_identity(
            "behavior_habit",
            {"action": "application.set_page_data_layout", "target_type": "application_module"},
            title="操作习惯：页面布局",
        )
        different = memory_identity(
            "behavior_habit",
            {"action": "application.set_page_data_notes", "target_type": "application_module"},
            title="操作习惯：页面便签",
        )
        self.assertEqual(first.merge_key, repeated.merge_key)
        self.assertNotEqual(first.merge_key, different.merge_key)

    def test_runtime_memory_supersedes_older_candidate_and_fuses_occurrences(self) -> None:
        store = InMemoryMemoryStore()
        self.addCleanup(store.close)
        first = MemoryRecord(
            memory_id="mem_old",
            memory_type="analysis_case",
            tenant_id="tenant_a",
            subject="在贷余额趋势",
            title="分析案例：在贷余额趋势",
            content={"memoryTopic": "在贷余额", "memoryAction": "trend", "conclusions": ["旧结论"]},
            verified_status="candidate",
            subject_type="tenant",
            subject_id="tenant_a",
            created_by="author_a",
        )
        second = MemoryRecord(
            memory_id="mem_new",
            memory_type="analysis_case",
            tenant_id="tenant_a",
            subject="在贷余额走势",
            title="分析案例：在贷余额走势",
            content={"memoryTopic": "在贷余额", "memoryAction": "trend", "conclusions": ["最新结论"]},
            verified_status="candidate",
            subject_type="tenant",
            subject_id="tenant_a",
            created_by="author_a",
        )
        self.assertTrue(store.write(first, force=True))
        self.assertTrue(store.write(second, force=True))
        self.assertEqual(store.get("tenant_a", "mem_old")["status"], "superseded")
        current = store.get("tenant_a", "mem_new")
        self.assertEqual(current["content"]["conclusions"], ["最新结论"])
        self.assertEqual(current["content"]["occurrenceCount"], 2)
        self.assertEqual(current["content"]["mergedFromMemoryIds"], ["mem_old"])


if __name__ == "__main__":
    unittest.main()
