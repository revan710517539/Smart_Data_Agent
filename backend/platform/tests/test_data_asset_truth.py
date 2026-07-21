import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from backend.platform.assets import InMemoryDataAssetStore, SQLiteDataAssetStore
from backend.platform.database import apply_migrations


class DataAssetTruthTest(unittest.TestCase):
    @staticmethod
    def topic_asset() -> dict:
        return {
            "id": "topic_candidate",
            "name": "Branch loan totals",
            "code": "branch_loan_totals",
            "description": "Tenant-scoped branch loan totals.",
            "sql": "SELECT branch_name, SUM(loan_amount) AS loan_amount FROM loan_fact WHERE tenant_id = :tenant_id GROUP BY branch_name",
            "fields": [
                {"fieldNameEn": "branch_name", "fieldNameCn": "Branch", "type": "string"},
                {"fieldNameEn": "loan_amount", "fieldNameCn": "Loan amount", "type": "decimal"},
            ],
        }

    def test_empty_store_never_materializes_demo_assets_on_read(self) -> None:
        store = InMemoryDataAssetStore(seed_defaults=False)
        bundle = store.list_bundle("tenant_empty")
        self.assertTrue(all(items == [] for items in bundle.values()))

    def test_deleting_last_asset_does_not_resurrect_defaults(self) -> None:
        store = InMemoryDataAssetStore(seed_defaults=False)
        store.upsert_item(
            "tenant_a",
            "intent",
            {
                "id": "intent_1",
                "scenario": "test scenario",
                "purpose": "test",
                "description": "test intent",
                "keywords": "test",
            },
        )
        self.assertTrue(store.delete_item("tenant_a", "intent", "intent_1"))
        self.assertEqual(store.list_bundle("tenant_a")["intents"], [])

    def test_system_weekly_topic_table_is_seeded_and_cannot_be_deleted(self) -> None:
        store = InMemoryDataAssetStore(seed_defaults=False)
        store.seed_defaults("tenant_a")
        topic = next(item for item in store.list_bundle("tenant_a")["topic_tables"] if item["id"] == "topic_core_weekly_metrics")
        self.assertEqual(topic["name"], "经营周报三指标")
        self.assertTrue(topic["systemManaged"])
        self.assertFalse(topic["deletable"])
        with self.assertRaisesRegex(PermissionError, "system_managed_data_asset_cannot_be_deleted"):
            store.delete_item("tenant_a", "topic_table", "topic_core_weekly_metrics")

    def test_sqlite_defaults_require_explicit_seed(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "platform.sqlite"
            apply_migrations(db_path)
            store = SQLiteDataAssetStore(db_path, initialize=False)
            try:
                self.assertEqual(store.list_bundle("tenant_demo")["raw_tables"], [])
                store.seed_defaults("tenant_demo")
                self.assertGreater(len(store.list_bundle("tenant_demo")["raw_tables"]), 0)
            finally:
                store.close()

    def test_candidate_is_not_reusable_until_four_eyes_approval(self) -> None:
        store = InMemoryDataAssetStore(seed_defaults=False)
        candidate = store.upsert_item(
            "tenant_a",
            "topic_table",
            self.topic_asset(),
            updated_by="author_a",
        )
        self.assertEqual(candidate["lifecycleStatus"], "review")
        self.assertEqual(store.list_published_bundle("tenant_a")["topic_tables"], [])
        with self.assertRaises(PermissionError):
            store.review_item(
                "tenant_a",
                "topic_table",
                "topic_candidate",
                decision="approved",
                reviewer_user_id="author_a",
                expected_version=1,
            )
        approved = store.review_item(
            "tenant_a",
            "topic_table",
            "topic_candidate",
            decision="approved",
            reviewer_user_id="reviewer_b",
            expected_version=1,
        )
        self.assertEqual(approved["lifecycleStatus"], "active")
        self.assertEqual(len(store.list_published_bundle("tenant_a")["topic_tables"]), 1)

    def test_sqlite_asset_versions_are_immutable_and_optimistically_reviewed(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "platform.sqlite"
            apply_migrations(db_path)
            store = SQLiteDataAssetStore(db_path, initialize=False)
            try:
                first = store.upsert_item(
                    "tenant_a",
                    "topic_table",
                    self.topic_asset(),
                    updated_by="author_a",
                )
                self.assertEqual(first["assetVersion"], 1)
                with self.assertRaises(RuntimeError):
                    store.review_item(
                        "tenant_a",
                        "topic_table",
                        "topic_candidate",
                        decision="approved",
                        reviewer_user_id="reviewer_b",
                        expected_version=99,
                    )
                approved = store.review_item(
                    "tenant_a",
                    "topic_table",
                    "topic_candidate",
                    decision="approved",
                    reviewer_user_id="reviewer_b",
                    expected_version=1,
                )
                self.assertEqual(approved["lifecycleStatus"], "active")
                revised = self.topic_asset()
                revised["description"] = "Revised candidate"
                second = store.upsert_item(
                    "tenant_a",
                    "topic_table",
                    revised,
                    updated_by="author_a",
                )
                self.assertEqual(second["assetVersion"], 2)
                self.assertEqual(second["lifecycleStatus"], "review")
                published = store.list_published_bundle("tenant_a")["topic_tables"]
                self.assertEqual(published[0]["description"], "Tenant-scoped branch loan totals.")
            finally:
                store.close()

    def test_topic_sql_requires_one_tenant_scoped_read_statement(self) -> None:
        store = InMemoryDataAssetStore(seed_defaults=False)
        unsafe = self.topic_asset()
        unsafe["sql"] = "DELETE FROM loan_fact"
        with self.assertRaisesRegex(ValueError, "topic_table_sql_must_be_select"):
            store.upsert_item("tenant_a", "topic_table", unsafe, updated_by="author_a")
        unscoped = self.topic_asset()
        unscoped["sql"] = "SELECT * FROM loan_fact"
        with self.assertRaisesRegex(ValueError, "tenant_binding_required"):
            store.upsert_item("tenant_a", "topic_table", unscoped, updated_by="author_a")

    def test_analysis_extensions_are_versioned_crud_assets(self) -> None:
        store = InMemoryDataAssetStore(seed_defaults=False)
        skill = store.upsert_item(
            "tenant_a",
            "analysis_skill",
            {
                "id": "scene_test",
                "name": "测试场景",
                "category": "场景",
                "description": "测试完整解决方案。",
                "memoryRefs": ["memory_a"],
                "toolRefs": ["tool_a"],
                "analysisMethod": "先核对口径再分析。",
                "documentAbstraction": "抽取时间、指标和机构。",
                "outputFormat": "结论 / 证据 / 动作",
                "viewpointStrategy": "结论必须有证据。",
                "recommendedSkillIds": [],
                "enabled": True,
                "sortOrder": 10,
            },
            updated_by="author_a",
        )
        tool = store.upsert_item(
            "tenant_a",
            "external_tool",
            {
                "id": "tool_a", "name": "外部工具", "provider": "test", "toolType": "api",
                "description": "测试工具。", "endpoint": "https://tool.example.test/api", "capabilities": ["query"],
                "enabled": True, "status": "已接入",
            },
            updated_by="author_a",
        )
        shortcut = store.upsert_item(
            "tenant_a",
            "analysis_shortcut",
            {
                "id": "shortcut_a", "title": "测试快捷键", "query": "执行测试分析",
                "skillIds": ["scene_test"], "tableIds": [], "visible": True,
                "sortOrder": 10, "ownerUserId": "u_a",
            },
            updated_by="author_a",
        )
        bundle = store.list_bundle("tenant_a")
        self.assertEqual(bundle["analysis_skills"][0]["analysisMethod"], "先核对口径再分析。")
        self.assertEqual(bundle["external_tools"][0]["capabilities"], ["query"])
        self.assertEqual(bundle["analysis_shortcuts"][0]["skillIds"], ["scene_test"])
        self.assertEqual((skill["assetVersion"], tool["assetVersion"], shortcut["assetVersion"]), (1, 1, 1))
        self.assertTrue(store.delete_item("tenant_a", "analysis_shortcut", "shortcut_a"))
        self.assertEqual(store.list_bundle("tenant_a")["analysis_shortcuts"], [])

    def test_external_system_requires_endpoint_before_enable(self) -> None:
        store = InMemoryDataAssetStore(seed_defaults=False)
        with self.assertRaisesRegex(ValueError, "external_tool_endpoint_required"):
            store.upsert_item(
                "tenant_a",
                "external_tool",
                {
                    "id": "tool_unconfigured",
                    "name": "未配置外部工具",
                    "provider": "Confluence",
                    "toolType": "knowledge_search",
                    "description": "缺少接入地址时不能启用。",
                    "endpoint": "",
                    "capabilities": ["query"],
                    "enabled": True,
                    "status": "已接入",
                },
                updated_by="author_a",
                lifecycle_status="active",
            )


if __name__ == "__main__":
    unittest.main()
