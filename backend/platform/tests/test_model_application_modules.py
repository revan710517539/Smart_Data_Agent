from __future__ import annotations

import unittest

from backend.platform.settings.model_modules import application_module_label, list_models_for_application, normalize_application_module
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.platform.settings.store import InMemorySystemConfigStore, SQLiteSystemConfigStore, account_system_config_scope


class ModelApplicationModuleTest(unittest.TestCase):
    @staticmethod
    def _model(model_id: str, name: str, module: str) -> dict[str, object]:
        return {
            "id": model_id,
            "name": name,
            "modelName": "中转站",
            "key": "https://relay.example/v1",
            "value": f"{model_id}-secret",
            "applicationModule": module,
            "availableModels": ["analysis-model"],
            "enabledModels": ["analysis-model"],
            "testStatus": "connected",
            "status": "available",
        }

    def test_saved_model_is_not_selectable_without_connectivity_test(self) -> None:
        store = InMemorySystemConfigStore()
        store.upsert_model(
            "tenant_demo",
            {
                "id": "model_untested",
                "name": "未测试模型",
                "modelName": "中转站",
                "key": "https://relay.example/v1",
                "value": "configured-secret",
                "applicationModule": "intelligent_analysis_reasoning",
                "testStatus": "untested",
                "status": "draft",
            },
        )

        models = list_models_for_application(store, "tenant_demo", "intelligent_analysis_reasoning")

        self.assertEqual(models, [])

    def test_connected_model_is_not_selectable_until_one_actual_submodel_is_enabled(self) -> None:
        store = InMemorySystemConfigStore()
        model = self._model("model_disabled", "已连接但未启用", "global_text_model")
        model["availableModels"] = ["analysis-model", "analysis-model-v2"]
        model["enabledModels"] = []
        store.upsert_model(account_system_config_scope("u_admin"), model, updated_by="u_admin")

        self.assertEqual(
            list_models_for_application(
                store,
                "tenant_demo",
                "intelligent_analysis_reasoning",
                user_id="u_admin",
            ),
            [],
        )

    def test_authenticated_account_scope_does_not_fall_back_to_tenant_binding(self) -> None:
        store = InMemorySystemConfigStore()
        configured = {
            "id": "model_shared",
            "name": "租户智能分析模型",
            "modelName": "relay",
            "key": "https://relay.example/v1",
            "value": "tenant-secret",
            "applicationModule": "intelligent_analysis_reasoning",
            "availableModels": ["analysis-model"],
            "enabledModels": ["analysis-model"],
            "testStatus": "connected",
            "status": "available",
        }
        store.upsert_model("tenant_demo", configured, updated_by="u_admin")
        store.upsert_model(
            account_system_config_scope("u_admin"),
            {
                **configured,
                "name": "账号历史副本",
                "applicationModule": "",
                "value": "account-secret",
            },
            updated_by="u_admin",
        )

        models = list_models_for_application(
            store,
            "tenant_demo",
            "intelligent_analysis_reasoning",
            user_id="u_admin",
            reveal_secret=True,
        )

        self.assertEqual([model["id"] for model in models], ["model_shared"])
        self.assertEqual(models[0]["applicationModule"], "intelligent_analysis_reasoning")
        self.assertEqual(models[0]["value"], "account-secret")

    def test_memory_module_has_one_current_binding_in_memory_store(self) -> None:
        store = InMemorySystemConfigStore()
        store.upsert_model("tenant_demo", self._model("memory_a", "记忆模型 A", "memory_extraction"))
        store.upsert_model("tenant_demo", self._model("memory_b", "记忆模型 B", "memory_extraction"))

        models = {item["id"]: item for item in store.list_models("tenant_demo")}
        self.assertEqual(models["memory_a"]["applicationModule"], "")
        self.assertEqual(models["memory_b"]["applicationModule"], "memory_extraction")
        self.assertEqual(
            [item["id"] for item in list_models_for_application(store, "tenant_demo", "memory_extraction")],
            ["memory_b"],
        )

    def test_memory_module_has_one_current_binding_in_sqlite_store(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSystemConfigStore(Path(tmpdir) / "settings.sqlite")
            try:
                store.upsert_model("tenant_demo", self._model("memory_a", "记忆模型 A", "memory_extraction"))
                store.upsert_model("tenant_demo", self._model("memory_b", "记忆模型 B", "memory_extraction"))
                models = {item["id"]: item for item in store.list_models("tenant_demo")}
                self.assertEqual(models["memory_a"]["applicationModule"], "")
                self.assertEqual(models["memory_b"]["applicationModule"], "memory_extraction")
            finally:
                store.close()

    def test_skill_evolution_module_placeholder_is_registered_without_model_binding(self) -> None:
        store = InMemorySystemConfigStore()
        self.assertEqual(normalize_application_module("Skill自学习与演化"), "skill_evolution_learning")
        self.assertEqual(application_module_label("skill_evolution_learning"), "Skill自学习与演化")
        self.assertEqual(list_models_for_application(store, "tenant_demo", "skill_evolution_learning"), [])

    def test_failed_model_is_retained_for_repair_but_not_routable(self) -> None:
        store = InMemorySystemConfigStore()
        failed_model = self._model("failed_relay", "待修复中转站", "global_text_model")
        failed_model["status"] = "draft"
        failed_model["testStatus"] = "failed"
        store.upsert_model("tenant_demo", failed_model)

        self.assertEqual(
            list_models_for_application(store, "tenant_demo", "intelligent_analysis_reasoning"),
            [],
        )

    def test_failed_global_relay_is_not_routable_after_first_connectivity_failure(self) -> None:
        store = InMemorySystemConfigStore()
        failed_default = self._model(
            "model_failed_global_relay",
            "失败的全局模型",
            "global_text_model",
        )
        failed_default["status"] = "draft"
        failed_default["testStatus"] = "failed"
        store.upsert_model(account_system_config_scope("u_admin"), failed_default)

        self.assertEqual(
            list_models_for_application(
                store,
                "tenant_demo",
                "automatic_analysis",
                user_id="u_admin",
            ),
            [],
        )

    def test_account_global_text_model_routes_to_every_non_voice_module_only(self) -> None:
        store = InMemorySystemConfigStore()
        account_scope = account_system_config_scope("u_admin")
        store.upsert_model(account_scope, self._model("global_relay", "账号全局模型", "global_text_model"))
        store.upsert_model("tenant_demo", self._model("legacy_tenant", "机构旧模型", "intelligent_analysis_reasoning"))

        for module in (
            "intelligent_analysis_reasoning",
            "weekly_report_conclusion_regeneration",
            "automatic_analysis",
            "memory_extraction",
            "skill_evolution_learning",
        ):
            self.assertEqual(
                [item["id"] for item in list_models_for_application(store, "tenant_demo", module, user_id="u_admin")],
                ["global_relay"],
            )
        self.assertEqual(
            list_models_for_application(store, "tenant_demo", "realtime_voice_input", user_id="u_admin"),
            [],
        )


if __name__ == "__main__":
    unittest.main()
