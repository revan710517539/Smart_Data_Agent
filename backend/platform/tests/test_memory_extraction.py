from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.platform.assets import InMemoryDataAssetStore
from backend.platform.api.routes.analysis import _build_asset_context, _related_detail_tables, _resolve_analysis_extensions
from backend.platform.lineage import InMemoryLineageStore
from backend.platform.memory.extraction import run_memory_extraction
from backend.platform.settings.model_modules import application_module_label, normalize_application_module


class _KnowledgeService:
    def list_documents(self, tenant_id: str):
        return [{"document_id": "kf_weekly_report_memory", "title": "周报分析口径记忆"}]

    def search(self, tenant_id: str, query: str, limit: int = 1):
        return [{"content": "周报先看规模，再看趋势和风险，汇报时先讲结论。"}]


class MemoryExtractionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryDataAssetStore()
        self.store.upsert_item(
            "tenant_demo", "knowledge_file",
            {"id": "kf_weekly_report_memory", "title": "周报分析口径记忆", "tags": "周报,口径"},
            updated_by="u_super_admin", lifecycle_status="active",
        )
        self.store.upsert_item(
            "tenant_demo", "analysis_experience",
            {"id": "exp_weekly_growth_quality", "title": "周报增长质量分析经验", "steps": "先核对口径，再比较趋势。"},
            updated_by="u_super_admin", lifecycle_status="active",
        )
        self.store.upsert_item(
            "tenant_demo", "topic_table",
            {
                "id": "topic_weekly_branch_rank", "name": "周报机构排名", "code": "weekly_branch_rank",
                "description": "受治理周报主题表。",
                "sql": "SELECT branch_name, loan_amount FROM weekly_branch_rank WHERE tenant_id = :tenant_id",
                "fields": [{"fieldNameEn": "branch_name", "fieldNameCn": "机构", "type": "string"}],
            },
            updated_by="u_super_admin", lifecycle_status="active",
        )
        self.services = SimpleNamespace(
            data_asset_store=self.store,
            knowledge_service=_KnowledgeService(),
            system_config_store=object(),
        )

    def test_theme_skill_does_not_require_output_format(self) -> None:
        item = {
            "id": "topic-test-no-format",
            "name": "无固定格式主题",
            "category": "主题",
            "description": "聚焦分析思路。",
            "memoryRefs": [],
            "toolRefs": [],
            "analysisMethod": "根据数据主题选择趋势、柱状或表格。",
            "documentAbstraction": "抽取对象、口径和证据。",
            "outputFormat": "",
            "viewpointStrategy": "区分事实与解释。",
            "recommendedSkillIds": [],
            "enabled": True,
            "sortOrder": 999,
        }
        saved = self.store.upsert_item("tenant_demo", "analysis_skill", item, updated_by="u_super_admin")
        self.assertEqual(saved["outputFormat"], "")

    def test_llm_mode_collects_sources_and_calls_model_once(self) -> None:
        response = {
            "intent": [{"scenario": "经营分析", "purpose": "周报", "description": "识别周报重点", "keywords": "周报,趋势"}],
            "analysis_experience": [{"title": "周报分析经验", "steps": "先规模，再趋势，再风险"}],
            "user_behavior_habit": [{"title": "结论先行", "habitType": "汇报习惯", "description": "先讲结论", "evidence": "周报文件"}],
        }
        with patch("backend.platform.memory.extraction.require_model_for_application", return_value={"id": "model-memory"}), patch(
            "backend.platform.memory.extraction.call_model_text_completion",
            return_value={
                "status": "connected",
                "response_text": json.dumps(response, ensure_ascii=False),
                "model_id": "model-memory",
                "used_model": "memory-model",
                "request_hash": "request-hash",
                "response_hash": "response-hash",
            },
        ) as completion:
            result = run_memory_extraction(
                self.services,
                "tenant_demo",
                "u_super_admin",
                {
                    "execution_mode": "llm",
                    "source_ids": ["kf_weekly_report_memory"],
                    "output_types": ["intent", "analysis_experience", "user_behavior_habit"],
                    "prompt": "提炼周报记忆",
                },
            )
        self.assertEqual(completion.call_count, 1)
        self.assertEqual(result["created_count"], 3)
        self.assertEqual(result["model_invocation"]["model_id"], "model-memory")
        created = self.store.list_bundle("tenant_demo")
        self.assertTrue(any(item["lifecycleStatus"] == "review" for item in created["behavior_habits"] if item["id"].startswith("mem_")))

    def test_script_mode_never_calls_model(self) -> None:
        with patch("backend.platform.memory.extraction.call_model_text_completion") as completion:
            result = run_memory_extraction(
                self.services,
                "tenant_demo",
                "u_super_admin",
                {
                    "execution_mode": "script",
                    "script_ref": "memory.rule_based_extraction.v1",
                    "source_ids": ["kf_weekly_report_memory"],
                    "output_types": ["analysis_experience"],
                },
            )
        completion.assert_not_called()
        self.assertEqual(result["created_count"], 1)
        self.assertIsNone(result["model_invocation"])

    def test_five_memory_outputs_are_saved_to_their_governed_destinations(self) -> None:
        response = {
            "analysis_experience": [{"title": "先识别口径差异", "description": "口径不一致时禁止直接比较", "steps": "先核对口径，再比较趋势"}],
            "intent": [{"scenario": "经营周报", "purpose": "识别异常", "description": "识别需要解释的趋势变化", "keywords": "周报,异常"}],
            "analysis_habit": [{"title": "先核对口径", "description": "指标比较前核对范围与时间", "evidence": "周报文件"}],
            "operation_habit": [{"title": "异常必须落动作", "description": "异常结论需配置负责人和截止时间", "evidence": "周报文件"}],
            "reporting_habit": [{"title": "结论先行", "description": "先汇报结论再展示证据", "evidence": "周报文件"}],
        }
        with patch("backend.platform.memory.extraction.require_model_for_application", return_value={"id": "model-memory"}), patch(
            "backend.platform.memory.extraction.call_model_text_completion",
            return_value={
                "status": "connected",
                "response_text": json.dumps(response, ensure_ascii=False),
                "model_id": "model-memory",
                "used_model": "memory-model",
                "request_hash": "request-hash-five",
                "response_hash": "response-hash-five",
            },
        ) as completion:
            result = run_memory_extraction(
                self.services,
                "tenant_demo",
                "u_super_admin",
                {
                    "execution_mode": "llm",
                    "source_kind": "knowledge_file",
                    "source_ids": ["kf_weekly_report_memory"],
                    "output_types": list(response),
                    "prompt": "只提炼本质内容",
                },
            )
        self.assertEqual(completion.call_count, 1)
        self.assertEqual(result["created_count"], 5)
        bundle = self.store.list_bundle("tenant_demo")
        extracted_habits = [item for item in bundle["behavior_habits"] if item["id"].startswith("mem_")]
        self.assertEqual({item["habitType"] for item in extracted_habits}, {"分析习惯", "运营习惯", "汇报习惯"})

    def test_unextracted_only_skips_current_version_and_reprocesses_updated_version(self) -> None:
        config = {
            "execution_mode": "script",
            "script_ref": "memory.rule_based_extraction.v1",
            "source_kind": "knowledge_file",
            "source_ids": ["kf_weekly_report_memory"],
            "output_types": ["analysis_experience"],
            "unextracted_only": True,
        }
        first = run_memory_extraction(self.services, "tenant_demo", "u_super_admin", config)
        second = run_memory_extraction(self.services, "tenant_demo", "u_super_admin", config)
        self.assertEqual(first["created_count"], 1)
        self.assertEqual(second["status"], "no_new_sources")
        self.assertEqual(second["created_count"], 0)

        current = next(item for item in self.store.list_bundle("tenant_demo")["knowledge_files"] if item["id"] == "kf_weekly_report_memory")
        self.store.upsert_item(
            "tenant_demo",
            "knowledge_file",
            {**current, "title": f"{current['title']}（更新）", "tags": f"{current.get('tags', '')},更新版本"},
            updated_by="u_super_admin",
            lifecycle_status="active",
        )
        updated = run_memory_extraction(self.services, "tenant_demo", "u_super_admin", config)
        self.assertEqual(updated["created_count"], 1)

    def test_llm_mode_accepts_knowledge_files_and_data_assets_in_one_call(self) -> None:
        response = {
            "intent": [{"scenario": "经营分析", "purpose": "数据资产分析", "description": "识别主题数据", "keywords": "周报"}],
            "analysis_experience": [],
            "user_behavior_habit": [],
        }
        with patch("backend.platform.memory.extraction.require_model_for_application", return_value={"id": "model-memory"}), patch(
            "backend.platform.memory.extraction.call_model_text_completion",
            return_value={
                "status": "connected",
                "response_text": json.dumps(response, ensure_ascii=False),
                "model_id": "model-memory",
                "used_model": "memory-model",
                "request_hash": "request-hash",
                "response_hash": "response-hash",
            },
        ) as completion:
            result = run_memory_extraction(
                self.services,
                "tenant_demo",
                "u_super_admin",
                {
                    "execution_mode": "llm",
                    "source_ids": ["kf_weekly_report_memory", "topic_weekly_branch_rank"],
                    "output_types": ["intent"],
                    "prompt": "联合提炼文件和主题数据",
                },
            )

        self.assertEqual(completion.call_count, 1)
        prompt = completion.call_args.args[1]
        self.assertIn('"source_type":"knowledge_file"', prompt)
        self.assertIn('"source_type":"topic_table"', prompt)
        self.assertEqual(result["source_ids"], ["kf_weekly_report_memory", "topic_weekly_branch_rank"])
        created = self.store.list_bundle("tenant_demo")["intents"]
        extracted = next(item for item in created if item["id"].startswith("mem_intent_"))
        self.assertIn("knowledge_file:kf_weekly_report_memory", extracted["sourceVersionId"])
        self.assertIn("topic_table:topic_weekly_branch_rank", extracted["sourceVersionId"])

    def test_memory_model_module_is_registered(self) -> None:
        self.assertEqual(normalize_application_module("记忆模块"), "memory_extraction")
        self.assertEqual(application_module_label("memory_extraction"), "记忆模块")

    def test_skill_runtime_never_resolves_knowledge_file_as_memory(self) -> None:
        self.store.upsert_item(
            "tenant_demo",
            "analysis_skill",
            {
                "id": "scene-memory-boundary",
                "name": "记忆边界",
                "category": "场景",
                "description": "验证知识文件边界。",
                "memoryRefs": ["kf_weekly_report_memory", "exp_weekly_growth_quality"],
                "toolRefs": [],
                "analysisMethod": "先验证记忆来源。",
                "documentAbstraction": "抽取证据。",
                "outputFormat": "结论 / 证据",
                "viewpointStrategy": "只引用可治理记忆。",
                "recommendedSkillIds": [],
                "enabled": True,
                "sortOrder": 999,
            },
            updated_by="u_super_admin",
            lifecycle_status="active",
        )
        resolved = _resolve_analysis_extensions(
            SimpleNamespace(data_asset_store=self.store),
            "tenant_demo",
            {"analysis_context_skills": [{"id": "scene-memory-boundary"}]},
        )
        memories = resolved["analysis_context_skills"][0]["memories"]
        self.assertEqual([memory["id"] for memory in memories], ["exp_weekly_growth_quality"])

    def test_analysis_memory_picker_accepts_direct_memory_and_rejects_file(self) -> None:
        services = SimpleNamespace(data_asset_store=self.store, metric_dictionary_store=None)
        context = _build_asset_context(
            services,
            "tenant_demo",
            "分析周报",
            {"analysis_memory_ids": ["exp_weekly_growth_quality"]},
        )
        self.assertEqual(context["analysis_memories"][0]["id"], "exp_weekly_growth_quality")
        with self.assertRaisesRegex(PermissionError, "selected_analysis_memory_not_published"):
            _build_asset_context(
                services,
                "tenant_demo",
                "分析周报",
                {"analysis_memory_ids": ["kf_weekly_report_memory"]},
            )

    def test_analysis_selected_csv_table_uses_same_catalog_as_picker(self) -> None:
        csv_table = {
            "id": "csv_current_delivery",
            "name": "当前交付 CSV",
            "code": "csv_current_delivery",
            "description": "Current tenant delivery.",
            "fields": [],
        }
        csv_source = SimpleNamespace(
            for_tenant=lambda tenant_id: SimpleNamespace(table_assets=lambda: [csv_table]),
        )
        services = SimpleNamespace(
            data_asset_store=self.store,
            metric_dictionary_store=None,
            data_acquisition_service=SimpleNamespace(csv_source=csv_source),
        )

        context = _build_asset_context(
            services,
            "tenant_demo",
            "分析当前交付",
            {"selected_data_tables": [{"id": "csv_current_delivery", "code": "csv_current_delivery"}]},
        )

        self.assertEqual([table["id"] for table in context["selected_data_tables"]], ["csv_current_delivery"])
        self.assertEqual(context["raw_table_count"], 1)

    def test_analysis_selected_csv_resolves_stale_delivery_by_source_key(self) -> None:
        current = {
            "id": "csv_current_delivery",
            "tableNameEn": "csv_current",
            "sourceKey": "990f5d708c26d1d0078d1b590803539e",
            "relativePath": "csv/yushu/2026-08-25/current.csv",
            "fields": [],
        }
        csv_source = SimpleNamespace(
            for_tenant=lambda tenant_id: SimpleNamespace(table_assets=lambda: [current]),
        )
        services = SimpleNamespace(
            data_asset_store=self.store,
            metric_dictionary_store=None,
            data_acquisition_service=SimpleNamespace(csv_source=csv_source),
        )

        context = _build_asset_context(
            services,
            "tenant_demo",
            "分析当前交付",
            {
                "selected_data_tables": [{
                    "id": "csv_old_delivery",
                    "code": "csv_old",
                    "kind": "raw",
                    "sourceKey": "990f5d708c26d1d0078d1b590803539e",
                    "relativePath": "csv/yushu/2026-08-14/old.csv",
                }],
            },
        )

        self.assertEqual(context["selected_data_tables"][0]["id"], "csv_current_delivery")
        self.assertEqual(context["selected_data_tables"][0]["relativePath"], current["relativePath"])
        with self.assertRaisesRegex(PermissionError, "selected_data_asset_not_published_or_not_authorized"):
            _build_asset_context(
                services,
                "tenant_demo",
                "分析已下线数据",
                {
                    "selected_data_tables": [{
                        "id": "csv_gone",
                        "code": "csv_gone",
                        "sourceKey": "missing_source_key",
                        "relativePath": "csv/yushu/2026-08-14/gone.csv",
                    }],
                },
            )

    def test_visual_follow_up_resolves_only_explicit_published_detail_table(self) -> None:
        lineage = InMemoryLineageStore()
        lineage.record_edge("tenant_demo", {
            "source_type": "dataset",
            "source_id": "detail_dataset",
            "target_type": "topic_table",
            "target_id": "topic_summary",
            "edge_type": "derives",
        })
        topic = {"id": "topic_summary", "name": "汇总主题表", "code": "summary"}
        detail = {"id": "raw_detail", "tableNameCn": "业务明细表", "tableNameEn": "detail", "datasetId": "detail_dataset", "relativePath": "tenant/detail.csv"}
        unrelated = {"id": "raw_other", "tableNameCn": "无关表", "tableNameEn": "other"}

        related = _related_detail_tables(
            SimpleNamespace(lineage_store=lineage),
            "tenant_demo",
            [topic],
            [topic, detail, unrelated],
        )

        self.assertEqual([item["id"] for item in related], ["raw_detail"])
        self.assertEqual(_related_detail_tables(SimpleNamespace(lineage_store=lineage), "tenant_demo", [unrelated], [topic, detail, unrelated]), [])


if __name__ == "__main__":
    unittest.main()
