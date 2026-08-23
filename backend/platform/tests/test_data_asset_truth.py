import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from types import SimpleNamespace

from backend.platform.assets import InMemoryDataAssetStore, SQLiteDataAssetStore
from backend.platform.api.routes.assets import _remove_deleted_skill_references
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

    def test_raw_table_external_reference_is_tenant_scoped_and_defaults_to_absent_private(self) -> None:
        store = InMemoryDataAssetStore(seed_defaults=False)
        source_key = "a" * 32
        schema = "b" * 32
        self.assertEqual(store.list_raw_table_external_references("tenant_a"), {})
        saved = store.set_raw_table_external_reference("tenant_a", source_key, "shared", schema, "owner_a")
        self.assertEqual(saved["mode"], "shared")
        self.assertEqual(store.list_raw_table_external_references("tenant_b"), {})
        self.assertEqual(store.list_raw_table_external_references("tenant_a")[source_key]["schemaFingerprint"], schema)

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

    def test_runtime_defaults_never_seed_sample_data_tables(self) -> None:
        store = InMemoryDataAssetStore(seed_defaults=False)
        store.seed_defaults("tenant_a")
        bundle = store.list_bundle("tenant_a")
        self.assertEqual(bundle["raw_tables"], [])
        self.assertEqual(bundle["topic_tables"], [])
        self.assertEqual(bundle["analysis_shortcuts"], [])

    def test_retired_sample_cleanup_is_id_scoped(self) -> None:
        store = InMemoryDataAssetStore(seed_defaults=False)
        store.upsert_item(
            "tenant_a",
            "raw_table",
            {
                "id": "raw_mock_customer_100",
                "tableNameEn": "retired_sample",
                "tableNameCn": "已退役样例",
                "source": "data/mock/retired.csv",
                "description": "Historical sample only.",
                "fields": [{"fieldNameEn": "id", "fieldNameCn": "ID", "type": "string"}],
            },
            updated_by="development_seed",
            lifecycle_status="active",
        )
        store.upsert_item(
            "tenant_a",
            "raw_table",
            {
                "id": "production_delivery",
                "tableNameEn": "production_delivery",
                "tableNameCn": "生产交付",
                "source": "delivery/production.csv",
                "description": "Production delivery.",
                "fields": [{"fieldNameEn": "id", "fieldNameCn": "ID", "type": "string"}],
            },
            updated_by="u_admin",
            lifecycle_status="active",
        )

        self.assertEqual(store.purge_retired_sample_assets("tenant_a"), 1)
        self.assertIsNone(store.get_item("tenant_a", "raw_table", "raw_mock_customer_100"))
        self.assertIsNotNone(store.get_item("tenant_a", "raw_table", "production_delivery"))

    def test_default_skill_scenes_can_be_deleted_without_bootstrap_resurrection(self) -> None:
        store = InMemoryDataAssetStore(seed_defaults=False)
        store.seed_defaults("tenant_a")
        self.assertIsNotNone(store.get_item("tenant_a", "analysis_skill", "scene-weekly-report"))
        self.assertEqual(
            {
                item["id"]
                for item in store.list_bundle("tenant_a")["analysis_skills"]
                if item.get("category") == "场景"
            },
            {
                "scene-analysis-intent",
                "scene-chart-followup",
                "scene-page-rail",
                "scene-textbox-voice",
                "scene-self-analysis",
            },
        )
        self.assertTrue(store.delete_item("tenant_a", "analysis_skill", "scene-weekly-report"))
        store.seed_missing_defaults("tenant_a")
        self.assertIsNone(store.get_item("tenant_a", "analysis_skill", "scene-weekly-report"))

    def test_sqlite_defaults_require_explicit_seed(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "platform.sqlite"
            apply_migrations(db_path)
            store = SQLiteDataAssetStore(db_path, initialize=False)
            try:
                self.assertEqual(store.list_bundle("tenant_demo")["raw_tables"], [])
                store.seed_defaults("tenant_demo")
                self.assertEqual(store.list_bundle("tenant_demo")["raw_tables"], [])
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

    def test_all_memory_list_item_types_keep_crud_versions_review_gated(self) -> None:
        store = InMemoryDataAssetStore(seed_defaults=False)
        cases = {
            "intent": (
                "intents",
                {"id": "intent_manual", "scenario": "经营分析", "purpose": "人工维护", "description": "初始意图内容", "keywords": "经营,维护"},
                "description",
            ),
            "knowledge_file": (
                "knowledge_files",
                {"id": "knowledge_manual", "title": "人工知识记忆", "content": "初始知识内容", "coverage": "待复核", "items": 1},
                "content",
            ),
            "analysis_experience": (
                "analysis_experiences",
                {"id": "experience_manual", "title": "人工分析经验", "steps": "先校验口径，再分析趋势。", "description": "初始经验内容"},
                "description",
            ),
            "user_behavior_habit": (
                "behavior_habits",
                {"id": "habit_manual", "title": "人工分析习惯", "habitType": "分析习惯", "description": "初始习惯内容", "sourceVersionId": "manual", "evidence": "人工维护"},
                "description",
            ),
        }

        for item_type, (bundle_key, payload, content_field) in cases.items():
            with self.subTest(item_type=item_type):
                candidate = store.upsert_item("tenant_a", item_type, payload, updated_by="author_a")
                self.assertEqual(candidate["lifecycleStatus"], "review")
                self.assertEqual(store.list_published_bundle("tenant_a")[bundle_key], [])

                approved = store.review_item(
                    "tenant_a",
                    item_type,
                    payload["id"],
                    decision="approved",
                    reviewer_user_id="reviewer_b",
                    expected_version=1,
                )
                revised_payload = {**approved, content_field: f"修订后的{item_type}内容"}
                revised = store.upsert_item("tenant_a", item_type, revised_payload, updated_by="author_a")
                self.assertEqual(revised["assetVersion"], 2)
                self.assertEqual(revised["lifecycleStatus"], "review")
                self.assertNotEqual(
                    store.list_published_bundle("tenant_a")[bundle_key][0][content_field],
                    revised_payload[content_field],
                )
                self.assertTrue(store.delete_item("tenant_a", item_type, payload["id"]))
                self.assertEqual(store.list_bundle("tenant_a")[bundle_key], [])

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

    def test_deleted_skill_references_are_removed_from_shortcuts(self) -> None:
        store = InMemoryDataAssetStore(seed_defaults=False)
        store.upsert_item(
            "tenant_a",
            "analysis_shortcut",
            {
                "id": "shortcut_a", "title": "测试快捷键", "query": "执行测试分析",
                "skillIds": ["scene_removed", "topic_kept"], "tableIds": [], "memoryIds": [],
                "visible": True, "sortOrder": 10, "ownerUserId": "u_a",
            },
            updated_by="author_a",
            lifecycle_status="active",
        )
        handler = SimpleNamespace(services=SimpleNamespace(data_asset_store=store))
        context = SimpleNamespace(tenant_id="tenant_a", user_id="u_admin")

        self.assertEqual(_remove_deleted_skill_references(handler, context, "scene_removed"), 1)
        shortcut = store.get_item("tenant_a", "analysis_shortcut", "shortcut_a")
        assert shortcut is not None
        self.assertEqual(shortcut["skillIds"], ["topic_kept"])
        self.assertEqual(shortcut["assetVersion"], 2)

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
