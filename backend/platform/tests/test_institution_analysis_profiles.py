from __future__ import annotations

import unittest

from backend.platform.analysis_profiles import (
    load_analysis_profiles,
    load_relational_tenant_codes_by_institution,
    seed_loan_analysis_candidates,
)
from backend.platform.api.routes.analysis import run_analysis
from backend.platform.assets.store import InMemoryDataAssetStore
from backend.platform.bootstrap import build_local_platform
from backend.platform.memory import InMemoryMemoryStore
from backend.platform.tests.governed_warehouse import attach_governed_test_warehouse


class InstitutionAnalysisProfilesTest(unittest.TestCase):
    def test_profile_tenant_ids_can_be_remapped_to_relational_catalog_codes(self) -> None:
        from backend.platform.analysis_profiles import remap_analysis_profile_tenants

        profiles = load_analysis_profiles()
        remapped = remap_analysis_profile_tenants(
            profiles,
            {
                "华兴银行": "tenant:huaxing",
                "广州银行": "tenant:guangzhou",
            },
        )
        by_name = {item["institution"]: item["tenantId"] for item in remapped["institutions"]}
        self.assertEqual(by_name["华兴银行"], "tenant:huaxing")
        self.assertEqual(by_name["广州银行"], "tenant:guangzhou")
        self.assertEqual(by_name["兰州银行"], "tenant:兰州银行")
        self.assertEqual(profiles["institutions"][0]["tenantId"], "tenant:华兴银行")

    def test_relational_catalog_loader_maps_active_names_and_ignores_inactive_rows(self) -> None:
        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def execute(self, sql):
                self.sql = sql

            def fetchall(self):
                return [
                    {"tenant_name": "华兴银行", "tenant_code": "tenant:huaxing"},
                    {"tenant_name": "广州银行", "tenant_code": "tenant:guangzhou"},
                ]

        class Connection:
            def cursor(self):
                return Cursor()

        self.assertEqual(
            load_relational_tenant_codes_by_institution(Connection()),
            {"华兴银行": "tenant:huaxing", "广州银行": "tenant:guangzhou"},
        )

    def test_runtime_kernel_seed_uses_relational_tenant_catalog_in_production(self) -> None:
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import patch

        from backend.platform.bootstrap import _bind_runtime_kernel

        class Pool:
            @contextmanager
            def connection(self):
                yield object()

        services = SimpleNamespace(
            runtime_config=SimpleNamespace(is_production=True),
            data_asset_store=object(),
            memory_store=object(),
            automation_runtime=object(),
            workflow=SimpleNamespace(),
        )
        profiles = {"institutions": [{"tenantId": "华兴银行"}]}
        mapped = {"institutions": [{"tenantId": "tenant:huaxing"}]}
        with patch.dict("os.environ", {"SMART_DATA_AGENT_CAPABILITY_MODE": "seed"}), \
             patch("backend.platform.analysis_profiles.load_analysis_profiles", return_value=profiles), \
             patch("backend.platform.analysis_profiles.load_relational_tenant_codes_by_institution", return_value={"华兴银行": "tenant:huaxing"}), \
             patch("backend.platform.analysis_profiles.remap_analysis_profile_tenants", return_value=mapped) as remap, \
             patch("backend.platform.analysis_profiles.prepare_loan_analysis_capabilities") as prepare, \
             patch("backend.platform.kernel.kernel.build_runtime_kernel", return_value=object()), \
             patch("backend.platform.kernel.jobs.register_runtime_jobs"):
            _bind_runtime_kernel(services, relational_pool=Pool())

        remap.assert_called_once_with(profiles, {"华兴银行": "tenant:huaxing"})
        self.assertEqual(prepare.call_args.kwargs["profiles"], mapped)

    def test_runtime_kernel_verify_uses_relational_tenant_catalog_in_production(self) -> None:
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import patch

        from backend.platform.bootstrap import _bind_runtime_kernel

        class Pool:
            @contextmanager
            def connection(self):
                yield object()

        services = SimpleNamespace(
            runtime_config=SimpleNamespace(is_production=True),
            data_asset_store=object(),
            memory_store=object(),
            automation_runtime=object(),
            workflow=SimpleNamespace(),
        )
        profiles = {"institutions": [{"tenantId": "tenant:华兴银行"}]}
        mapped = {"institutions": [{"tenantId": "tenant:huaxing"}]}
        with patch.dict("os.environ", {"SMART_DATA_AGENT_CAPABILITY_MODE": "verify"}), \
             patch("backend.platform.analysis_profiles.load_analysis_profiles", return_value=profiles), \
             patch("backend.platform.analysis_profiles.load_relational_tenant_codes_by_institution", return_value={"华兴银行": "tenant:huaxing"}), \
             patch("backend.platform.analysis_profiles.remap_analysis_profile_tenants", return_value=mapped) as remap, \
             patch("backend.platform.analysis_profiles.verify_loan_analysis_capabilities") as verify, \
             patch("backend.platform.kernel.kernel.build_runtime_kernel", return_value=object()), \
             patch("backend.platform.kernel.jobs.register_runtime_jobs"):
            _bind_runtime_kernel(services, relational_pool=Pool())

        remap.assert_called_once_with(profiles, {"华兴银行": "tenant:huaxing"})
        self.assertEqual(verify.call_args.kwargs["profiles"], mapped)

    def test_import_merges_33_methods_into_canonical_skills_and_110_memories(self) -> None:
        assets = InMemoryDataAssetStore(seed_defaults=False)
        memories = InMemoryMemoryStore()
        self.addCleanup(memories.close)
        result = seed_loan_analysis_candidates(assets, memories)
        self.assertEqual(result, {"skills_merged": 33, "institution_skills_archived": 0, "memories_created": 110})
        self.assertEqual(seed_loan_analysis_candidates(assets, memories), {"skills_merged": 0, "institution_skills_archived": 0, "memories_created": 0})
        for profile in load_analysis_profiles()["institutions"]:
            tenant_id = profile["tenantId"]
            skills = assets.list_bundle(tenant_id)["analysis_skills"]
            canonical = [item for item in skills if item["id"] in {"topic-descriptive", "topic-attribution", "topic-predictive"}]
            self.assertEqual({item["name"] for item in canonical}, {"描述性分析", "归因分析", "预测分析"})
            self.assertTrue(all(item["lifecycleStatus"] == "active" and len(item["memoryRefs"]) >= 10 for item in canonical))
            self.assertFalse(any(str(item["id"]).startswith("institution.") for item in skills))
            self.assertEqual(len([item for item in assets.list_published_bundle(tenant_id)["analysis_skills"] if item["id"] in {"topic-descriptive", "topic-attribution", "topic-predictive"}]), 3)
            tenant_memories = memories.search(tenant_id, statuses=("candidate",), limit=20)
            self.assertEqual(len(tenant_memories), 10)
            self.assertTrue(all(item.subject_id == tenant_id for item in tenant_memories))

    def test_institution_named_core_method_cannot_be_created_as_another_skill(self) -> None:
        assets = InMemoryDataAssetStore(seed_defaults=False)
        with self.assertRaisesRegex(ValueError, "data_asset_duplicate_core_topic_skill:topic-descriptive"):
            assets.upsert_item(
                "tenant:华兴银行",
                "analysis_skill",
                {
                    "id": "institution.huaxing.descriptive",
                    "name": "华兴银行描述性分析",
                    "category": "主题",
                    "description": "重复能力",
                    "memoryRefs": [],
                    "toolRefs": [],
                    "analysisMethod": "描述现状。",
                    "documentAbstraction": "抽取字段。",
                    "outputFormat": "",
                    "viewpointStrategy": "基于证据。",
                    "recommendedSkillIds": [],
                    "enabled": True,
                    "sortOrder": 300,
                },
                updated_by="u_super_admin",
                lifecycle_status="review",
            )

    def test_skill_display_location_is_strictly_validated(self) -> None:
        assets = InMemoryDataAssetStore(seed_defaults=False)
        with self.assertRaisesRegex(ValueError, "data_asset_invalid_analysis_skill_display_location"):
            assets.upsert_item(
                "tenant:华兴银行",
                "analysis_skill",
                {
                    "id": "topic-new-method",
                    "name": "新的分析思路",
                    "category": "主题",
                    "description": "区别于既有四类分析的独立方法。",
                    "memoryRefs": [],
                    "toolRefs": [],
                    "analysisMethod": "按新方法执行。",
                    "documentAbstraction": "提炼方法输入。",
                    "outputFormat": "",
                    "viewpointStrategy": "保留证据边界。",
                    "recommendedSkillIds": [],
                    "enabled": True,
                    "displayLocation": "weekly_report",
                    "sortOrder": 500,
                },
                updated_by="u_super_admin",
                lifecycle_status="active",
            )

    def test_runtime_executes_scene_method_through_unified_executor(self) -> None:
        services = build_local_platform()
        self.addCleanup(services.close)
        attach_governed_test_warehouse(services)
        payload = run_analysis(
            services,
            user_id="u_super_admin",
            tenant_id="tenant_demo",
            question="各分行放款金额为什么不同，请做归因分析",
        )
        methods = payload["skill_results"][0]["analysis_methods"]
        self.assertEqual([item["kind"] for item in methods], ["attribution"])
        self.assertEqual(methods[0]["causal_status"], "contribution_only")
        self.assertEqual(methods[0]["evidence_boundary"]["claim_level"], "evidence_bound")
        spans = services.trace_recorder.spans()
        self.assertTrue(any(span.name == "skill.execute.start" and span.inputs.get("skill_id") == "data.analysis.attribution" for span in spans))


if __name__ == "__main__":
    unittest.main()
