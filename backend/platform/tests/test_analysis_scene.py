from __future__ import annotations

import unittest

from backend.platform.api.routes.analysis import _relevant_analysis_memories, run_analysis
from backend.platform.assets.store import SCENE_INTENT_SKILL_ID, InMemoryDataAssetStore
from backend.platform.bootstrap import build_local_platform
from backend.platform.kernel.scene import (
    KIND_ATTRIBUTION,
    KIND_DESCRIPTIVE,
    KIND_PREDICTIVE,
    SURFACE_CHART_FOLLOWUP,
    SURFACE_PAGE_RAIL,
    SURFACE_SELF_ANALYSIS,
    SURFACE_TEXTBOX_VOICE,
    VOICE_TEXTBOX_RECORD,
    apply_analysis_scene,
    classify_analysis_scene,
    plan_analysis_skills,
)
from backend.platform.tenancy import ExecutionContext
from backend.platform.tests.governed_warehouse import attach_governed_test_warehouse


class AnalysisSceneTest(unittest.TestCase):
    def test_chart_followup_and_page_rail_surfaces(self) -> None:
        chart = classify_analysis_scene("这个指标为什么下降", {"visual_analysis_scope": "chart", "chart_bound_source": True})
        self.assertEqual(chart.surface, SURFACE_CHART_FOLLOWUP)
        self.assertEqual(chart.dataset_scope, "chart")
        self.assertIn(KIND_ATTRIBUTION, chart.analysis_kinds)
        page = classify_analysis_scene("看一下整体情况", {"visual_analysis_scope": "page", "analysis_scene_hint": "page_rail", "workspace_id": "ws_page"})
        self.assertEqual(page.surface, SURFACE_PAGE_RAIL)
        self.assertEqual(page.dataset_scope, "page")
        self.assertIn(KIND_DESCRIPTIVE, page.analysis_kinds)

    def test_textbox_voice_always_transcribes_without_analysis(self) -> None:
        record = classify_analysis_scene("记下今天的口径说明", {"visual_card_type": "text", "analysis_trigger": "realtime_voice_silence", "voice_surface": "text"})
        self.assertEqual(record.surface, SURFACE_TEXTBOX_VOICE)
        self.assertEqual(record.voice_mode, VOICE_TEXTBOX_RECORD)
        self.assertEqual(record.action, "record")
        analyze = classify_analysis_scene("分析一下放款为什么下降，并预测下月", {"visual_card_type": "text", "analysis_trigger": "realtime_voice_silence", "voice_surface": "text"})
        self.assertEqual(analyze.voice_mode, VOICE_TEXTBOX_RECORD)
        self.assertEqual(analyze.action, "record")
        self.assertEqual(analyze.analysis_kinds, ())

    def test_planner_schedules_scene_split_and_kind_skills(self) -> None:
        catalog = [
            {"id": "topic-descriptive", "name": "描述性分析", "enabled": True, "updatedBy": "development_seed"},
            {"id": "topic-attribution", "name": "归因分析", "enabled": True, "updatedBy": "development_seed"},
            {"id": "loan-attribution-local", "name": "消费贷归因", "enabled": True, "displayLocation": "hidden", "updatedBy": "u_local", "description": "归因"},
        ]
        generic = plan_analysis_skills(classify_analysis_scene("放款金额按机构看一看", {"route": "self-analysis/query"}), catalog, "放款金额按机构看一看")
        self.assertEqual(generic.surface, SURFACE_SELF_ANALYSIS)
        self.assertEqual(generic.skill_ids[0], SCENE_INTENT_SKILL_ID)
        self.assertIn("scene-self-analysis", generic.skill_ids)
        self.assertIn("topic-descriptive", generic.skill_ids)
        followup = plan_analysis_skills(classify_analysis_scene("这个指标为什么下降", {"visual_analysis_scope": "chart", "chart_bound_source": True}), catalog, "这个指标为什么下降")
        self.assertIn("scene-chart-followup", followup.skill_ids)
        attributed = plan_analysis_skills(classify_analysis_scene("为什么逾期上升", {"route": "self-analysis/query"}), catalog, "为什么逾期上升")
        self.assertIn("loan-attribution-local", attributed.skill_ids)
        record = plan_analysis_skills(classify_analysis_scene("记下今天的口径说明", {"visual_card_type": "text", "analysis_trigger": "realtime_voice_silence", "voice_surface": "text"}), catalog, "记下今天的口径说明")
        self.assertIn("scene-textbox-voice", record.skill_ids)
        self.assertNotIn("topic-descriptive", record.skill_ids)

    def test_apply_scene_keeps_planner_first(self) -> None:
        context = apply_analysis_scene(
            "各分行放款金额",
            {"route": "self-analysis/query", "analysis_skill": {"id": "page-funnel"}, "analysis_context_skills": [{"id": "page-funnel"}]},
            [],
        )
        self.assertEqual(context["analysis_scene"]["planner_skill_id"], SCENE_INTENT_SKILL_ID)
        self.assertIn(SCENE_INTENT_SKILL_ID, context["analysis_scene"]["skill_ids"])
        ids = [str(item.get("id") or "") for item in context["analysis_context_skills"]]
        self.assertEqual(ids[0], "page-funnel")
        self.assertIn("scene-self-analysis", ids)
        self.assertIn("topic-descriptive", ids)

    def test_explicit_page_skill_still_dispatches_scene_and_topic_skills(self) -> None:
        context = apply_analysis_scene(
            "为什么消费贷逾期率上升",
            {
                "analysis_scene_hint": "page_rail",
                "workspace_id": "ws_page",
                "analysis_context_skills": [{"id": "page-customers", "name": "客群分析页面追问", "category": "场景"}],
            },
            [],
        )
        ids = [str(item.get("id") or "") for item in context["analysis_context_skills"]]
        self.assertEqual(ids[0], "page-customers")
        self.assertIn("scene-page-rail", ids)
        self.assertIn("topic-attribution", ids)

    def test_question_relevant_memory_is_ranked_without_exposing_unrelated_memory(self) -> None:
        memories = [
            {"id": "m_overdue", "title": "逾期风险拆解", "keywords": "逾期率,风险", "description": "按产品和客群分析"},
            {"id": "m_report", "title": "日报排版习惯", "keywords": "日报,排版", "description": "日报模板"},
        ]
        ranked = _relevant_analysis_memories("为什么消费贷逾期率上升", memories)
        self.assertEqual([item["id"] for item in ranked], ["m_overdue"])

    def test_scene_intent_skill_is_visible_in_plugin_catalog(self) -> None:
        store = InMemoryDataAssetStore(seed_defaults=True)
        demo = [item["id"] for item in store.list_bundle("tenant_demo")["analysis_skills"]]
        self.assertIn(SCENE_INTENT_SKILL_ID, demo)
        other = InMemoryDataAssetStore(seed_defaults=False)
        other.seed_missing_defaults("tenant:三峡银行")
        plugin_ids = {item["id"] for item in other.list_bundle("tenant:三峡银行")["analysis_skills"]}
        self.assertTrue({"scene-analysis-intent", "scene-chart-followup", "scene-page-rail", "scene-textbox-voice", "topic-descriptive", "topic-attribution", "topic-predictive"}.issubset(plugin_ids))

    def test_run_analysis_records_scene_and_keeps_model_planning(self) -> None:
        services = build_local_platform()
        self.addCleanup(services.close)
        attach_governed_test_warehouse(services)
        payload = run_analysis(
            services,
            user_id="u_super_admin",
            tenant_id="tenant_demo",
            question="放款金额按机构看一看",
            page_context={"route": "self-analysis/query"},
        )
        scene = payload.get("analysis_scene") or {}
        self.assertEqual(scene.get("surface"), SURFACE_SELF_ANALYSIS)
        self.assertIn(KIND_DESCRIPTIVE, scene.get("analysis_kinds") or [])
        self.assertIn(SCENE_INTENT_SKILL_ID, scene.get("skill_ids") or [])
        self.assertTrue(str(payload.get("pack_snapshot_id") or "").startswith("pack_"))

    def test_bind_request_without_prior_scene_still_classifies(self) -> None:
        services = build_local_platform()
        self.addCleanup(services.close)
        context = ExecutionContext(
            "u_super_admin",
            "tenant_demo",
            page_context={"question": "看下整体情况", "visual_analysis_scope": "page", "analysis_scene_hint": "page_rail", "workspace_id": "ws_page"},
        )
        services.runtime_kernel.bind_request(context)
        self.assertEqual(context.page_context["analysis_scene"]["surface"], SURFACE_PAGE_RAIL)


if __name__ == "__main__":
    unittest.main()
