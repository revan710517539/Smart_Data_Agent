from __future__ import annotations

import unittest

from backend.authz import normalize_tenant_id
from backend.platform.assets.store import InMemoryDataAssetStore


class TenantCatalogIsolationTest(unittest.TestCase):
    def test_other_institution_tools_and_cloned_default_skills_are_hidden(self) -> None:
        store = InMemoryDataAssetStore(seed_defaults=False)
        shizuishan = normalize_tenant_id("石嘴山银行")
        huaxing = normalize_tenant_id("华兴银行")

        store.seed_defaults(shizuishan, updated_by="system")
        store.upsert_item(
            shizuishan,
            "external_tool",
            {
                "id": "tool_yushu_my_queries_sync",
                "name": "华兴毓数我的查询 SQL 同步",
                "provider": "毓数",
                "toolType": "api",
                "description": "同步毓数查询",
                "endpoint": "https://tools.example/yushu",
                "capabilities": ["sql"],
                "enabled": True,
                "status": "已接入",
            },
            updated_by="system",
        )
        store.upsert_item(
            shizuishan,
            "external_tool",
            {
                "id": "tool_focuspro_business_sandbox_crawler",
                "name": "华兴银行经营沙盘数据获取",
                "provider": "智能运营",
                "toolType": "api",
                "description": "华兴银行经营沙盘",
                "endpoint": "https://tools.example/sandbox",
                "capabilities": ["crawl"],
                "enabled": True,
                "status": "已接入",
            },
            updated_by="system",
        )
        store.upsert_item(
            huaxing,
            "external_tool",
            {
                "id": "tool_focuspro_business_sandbox_crawler",
                "name": "华兴银行经营沙盘数据获取",
                "provider": "智能运营",
                "toolType": "api",
                "description": "华兴银行经营沙盘",
                "endpoint": "https://tools.example/sandbox",
                "capabilities": ["crawl"],
                "enabled": True,
                "status": "已接入",
            },
            updated_by="system",
        )
        store.upsert_item(
            shizuishan,
            "analysis_skill",
            {
                "id": "scene_local",
                "name": "石嘴山本地场景",
                "category": "场景",
                "description": "本机构自建场景",
                "memoryRefs": [],
                "toolRefs": [],
                "analysisMethod": "按本机构数据核对。",
                "documentAbstraction": "抽取本机构字段。",
                "outputFormat": "结论 / 证据",
                "viewpointStrategy": "只使用本机构证据。",
                "recommendedSkillIds": [],
                "enabled": True,
                "sortOrder": 1,
            },
            updated_by="u_local",
        )

        isolated = store.list_bundle(shizuishan)
        huaxing_bundle = store.list_bundle(huaxing)

        names = {item["name"] for item in isolated["analysis_skills"]}
        self.assertIn("场景分析判断", names)
        self.assertIn("图表追问分析", names)
        self.assertIn("整页AI分析", names)
        self.assertIn("文本框实时语音", names)
        self.assertIn("智能分析主查询", names)
        self.assertIn("描述性分析", names)
        self.assertIn("归因分析", names)
        self.assertIn("预测分析", names)
        self.assertIn("石嘴山本地场景", names)
        self.assertNotIn("周报分析", names)
        self.assertEqual(isolated["external_tools"], [])
        self.assertEqual(isolated["analysis_shortcuts"], [])
        self.assertIn("华兴银行经营沙盘数据获取", [item["name"] for item in huaxing_bundle["external_tools"]])

    def test_empty_operating_tenant_does_not_receive_cloned_skill_catalog(self) -> None:
        store = InMemoryDataAssetStore(seed_defaults=False)
        shizuishan = normalize_tenant_id("石嘴山银行")
        store.seed_missing_defaults(shizuishan)
        skill_ids = {item["id"] for item in store.list_bundle(shizuishan)["analysis_skills"]}
        self.assertEqual(
            skill_ids,
            {
                "scene-analysis-intent",
                "scene-chart-followup",
                "scene-page-rail",
                "scene-textbox-voice",
                "scene-self-analysis",
                "topic-descriptive",
                "topic-attribution",
                "topic-predictive",
            },
        )
        self.assertEqual(store.list_bundle(shizuishan)["external_tools"], [])
        self.assertEqual(store.list_bundle(shizuishan)["analysis_shortcuts"], [])
        self.assertIsNone(store.get_item(shizuishan, "analysis_skill", "scene-weekly-report"))


if __name__ == "__main__":
    unittest.main()
