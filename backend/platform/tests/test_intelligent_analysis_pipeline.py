from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backend.platform.api.routes import run_analysis
from backend.platform.bootstrap import build_local_platform
from backend.platform.intelligent_analysis import IntelligentAnalysisEngine
from backend.platform.intelligent_analysis.engine import IntelligentAnalysisRequest
from backend.platform.settings.store import account_system_config_scope
from backend.platform.tests.governed_warehouse import attach_governed_test_warehouse


class IntelligentAnalysisPipelineTest(unittest.TestCase):
    def test_invalid_planning_json_retries_with_compact_prompt(self) -> None:
        valid = json.dumps({
            "metrics": ["loan_amount"], "dimensions": ["branch_name"], "limit": 10,
            "sort_direction": "desc", "sql": "select branch_name from loan_operation_fact where tenant_id = :tenant_id",
            "data_processing_python": "def process_data(data, context):\n    return {\"rows\": data, \"quality\": {}}\n",
            "visualization_python": "def build_chart(data, context):\n    return {\"type\": \"bar\", \"series\": data}\n",
            "analysis_approach": ["核对口径"], "metric_scenarios": [], "visualization_suggestions": [],
        }, ensure_ascii=False)
        request = IntelligentAnalysisRequest(
            question="分行放款金额",
            tenant_id="tenant_demo",
            user_id="u_super_admin",
            analysis_plan={"dataset_id": "loan_operation_mart", "metrics": ["loan_amount"], "dimensions": ["branch_name"], "limit": 10, "chart_types": ["bar"]},
            model={"id": "model_two_stage", "name": "两阶段分析模型"},
        )
        with patch(
            "backend.platform.intelligent_analysis.engine.call_model_text_completion",
            side_effect=[
                {"status": "connected", "response_text": '{"metrics":["loan_amount"],"sql":"unterminated'},
                {"status": "connected", "response_text": valid, "request_hash": "a" * 64, "response_hash": "b" * 64},
            ],
        ) as completion:
            planning = IntelligentAnalysisEngine().plan(request)
        self.assertEqual(completion.call_count, 2)
        self.assertEqual(planning["planning_source"], "model")
        self.assertEqual(planning["planning_invocation"]["retry_count"], 1)
        self.assertIn("总输出不超过 9000 个字符", completion.call_args_list[1].args[1])

    def test_invalid_final_json_retries_with_compact_prompt(self) -> None:
        valid = json.dumps(
            {
                "analysis_summary": "自动重试后已基于实际查询证据生成结论。",
                "conclusions": ["华东分行本次返回值最高。"],
                "metric_findings": [],
                "visualization_suggestions": [],
            },
            ensure_ascii=False,
        )
        request = IntelligentAnalysisRequest(
            question="比较各分行放款金额",
            tenant_id="tenant_demo",
            user_id="u_super_admin",
            model={"id": "model_two_stage", "name": "两阶段分析模型"},
            query_result={"data": [{"branch_name": "华东分行", "metric_value": 100}]},
        )
        with patch(
            "backend.platform.intelligent_analysis.engine.call_model_text_completion",
            side_effect=[
                {"status": "connected", "response_text": '{"analysis_summary":"unterminated'},
                {"status": "connected", "response_text": valid},
            ],
        ) as completion:
            result = IntelligentAnalysisEngine().analyze(request, {"visualization_suggestions": []})

        self.assertEqual(completion.call_count, 2)
        self.assertEqual(result["analysis_summary"], "自动重试后已基于实际查询证据生成结论。")
        self.assertEqual(result["model_invocation"]["status"], "connected")
        self.assertEqual(result["model_invocation"]["retry_count"], 1)
        self.assertEqual(result["model_invocation"]["initial_error_code"], "model_final_output_invalid")
        self.assertIn("仅返回一个闭合的 JSON 对象", completion.call_args_list[1].args[1])

    def test_invalid_final_json_after_retry_uses_evidence_based_fallback(self) -> None:
        request = IntelligentAnalysisRequest(
            question="比较各分行放款金额",
            tenant_id="tenant_demo",
            user_id="u_super_admin",
            model={"id": "model_two_stage", "name": "两阶段分析模型"},
            query_result={"data": [{"branch_name": "华东分行", "metric_value": 100}]},
        )
        with patch(
            "backend.platform.intelligent_analysis.engine.call_model_text_completion",
            side_effect=[
                {"status": "connected", "response_text": '{"analysis_summary":"unterminated'},
                {"status": "connected", "response_text": '{"analysis_summary":"still unterminated'},
            ],
        ):
            result = IntelligentAnalysisEngine().analyze(request, {"visualization_suggestions": []})

        self.assertTrue(result["analysis_summary"])
        self.assertTrue(result["possible_conclusions"])
        self.assertEqual(result["model_invocation"]["status"], "failed")
        self.assertEqual(result["model_invocation"]["error_code"], "model_final_output_invalid")
        self.assertEqual(result["model_invocation"]["retry_count"], 1)

    def test_empty_query_result_skips_slow_model_conclusion(self) -> None:
        request = IntelligentAnalysisRequest(
            question="分析本周经营周报",
            tenant_id="tenant_demo",
            user_id="u_super_admin",
            model={"id": "model_two_stage", "name": "两阶段分析模型"},
            analysis_plan={"metrics": ["loan_amount"], "dimensions": ["branch_name"]},
            query_result={
                "data": [],
                "evidence": {"evidence_id": "ev_empty_result"},
                "semantic_info": {"schema_mapping": {"metrics": ["loan_amount"], "dimensions": ["branch_name"]}},
            },
        )
        with patch("backend.platform.intelligent_analysis.engine.call_model_text_completion") as completion:
            result = IntelligentAnalysisEngine().analyze(request, {"visualization_suggestions": [{"type": "column"}]})

        completion.assert_not_called()
        self.assertEqual(result["model_invocation"]["status"], "skipped")
        self.assertEqual(result["model_invocation"]["reason"], "empty_query_result")
        self.assertEqual(result["visualization_suggestions"], [])
        self.assertIn("未返回可用于分析", result["analysis_summary"])

    def setUp(self) -> None:
        self.services = build_local_platform()
        attach_governed_test_warehouse(self.services)
        self.services.system_config_store.upsert_model(
            account_system_config_scope("u_super_admin"),
            {
                "id": "model_two_stage",
                "name": "两阶段分析模型",
                "modelName": "finance-analysis-v2",
                "key": "https://example.local/v1",
                "value": "test-secret",
                "availableModels": ["finance-analysis-v2"],
                "enabledModels": ["finance-analysis-v2"],
                "applicationModule": "intelligent_analysis_reasoning",
                "testStatus": "connected",
                "status": "available",
            },
            updated_by="u_super_admin",
        )

    def tearDown(self) -> None:
        self.services.close()

    def test_selected_model_plans_before_query_and_analyzes_actual_evidence_after_query(self) -> None:
        model_python = '''def build_chart(data, context):
    return {
        "type": "line",
        "title": "模型规划图",
        "x": context.get("x", "branch_name"),
        "y": context.get("y", "metric_value"),
        "series": data,
        "table_rows": data,
    }
'''
        planning_json = json.dumps(
            {
                "metrics": ["loan_amount"],
                "dimensions": ["branch_name"],
                "limit": 10,
                "sort_direction": "desc",
                "sql": (
                    "SELECT branch_name, SUM(loan_amount) AS loan_amount "
                    "FROM loan_operation_fact WHERE tenant_id = :tenant_id GROUP BY branch_name"
                ),
                "python_script": model_python,
                "analysis_approach": ["先核对放款金额口径", "再比较分行排名并检查集中度"],
                "metric_scenarios": [
                    {
                        "metric": "loan_amount",
                        "positive": "高于目标时检查增量来源",
                        "neutral": "平稳时检查结构变化",
                        "negative": "下降时拆解机构与产品贡献",
                    }
                ],
                "visualization_suggestions": [
                    {
                        "type": "line",
                        "title": "分行放款金额",
                        "dimension": "branch_name",
                        "metric": "loan_amount",
                        "purpose": "展示实际分行差异",
                    }
                ],
            },
            ensure_ascii=False,
        )
        final_json = json.dumps(
            {
                "analysis_summary": "核心结论：上海分行放款金额领先。\n数据证据：引用实际查询证据。\n原因边界：仅依据本次返回数据。\n经营建议：复核增量来源。\n风险提示：不得外推未返回期间。\n后续动作：持续跟踪。",
                "conclusions": ["上海分行放款金额在本次返回数据中领先。"],
                "metric_findings": [
                    {
                        "metric": "loan_amount",
                        "observed": "排名第一",
                        "interpretation": "领先",
                        "evidence": "metric_value",
                    }
                ],
                "visualization_suggestions": [
                    {
                        "type": "line",
                        "title": "分行放款金额",
                        "dimension": "branch_name",
                        "metric": "loan_amount",
                        "purpose": "展示实际分行差异",
                    }
                ],
            },
            ensure_ascii=False,
        )
        completions = [
            {
                "status": "connected",
                "model_id": "model_two_stage",
                "used_model": "finance-analysis-v2",
                "request_hash": "1" * 64,
                "response_hash": "2" * 64,
                "response_text": planning_json,
                "latency_ms": 12,
            },
            {
                "status": "connected",
                "model_id": "model_two_stage",
                "used_model": "finance-analysis-v2",
                "request_hash": "3" * 64,
                "response_hash": "4" * 64,
                "response_text": final_json,
                "latency_ms": 15,
            },
        ]

        with patch(
            "backend.platform.intelligent_analysis.engine.call_model_text_completion",
            side_effect=completions,
        ) as completion:
            response = run_analysis(
                self.services,
                user_id="u_super_admin",
                tenant_id="tenant_demo",
                question="2026年7月各分行放款金额排名TOP10",
                page_context={"selected_model": {"id": "model_two_stage"}},
            )

        self.assertEqual(completion.call_count, 2)
        planning_prompt = completion.call_args_list[0].args[1]
        final_prompt = completion.call_args_list[1].args[1]
        self.assertIn("第一阶段", planning_prompt)
        self.assertIn("实际执行证据", final_prompt)
        self.assertIn("source_snapshot", final_prompt)
        intelligent = response["intelligent_analysis"]
        self.assertEqual(intelligent["planning"]["planning_source"], "model")
        self.assertEqual(intelligent["planning_invocation"]["status"], "connected")
        self.assertEqual(intelligent["model_invocation"]["status"], "connected")
        self.assertEqual(intelligent["analysis_summary"], json.loads(final_json)["analysis_summary"])
        self.assertEqual(intelligent["metric_scenarios"][0]["metric"], "loan_amount")
        self.assertEqual(response["skill_results"][0]["python_script"].strip(), model_python.strip())
        self.assertEqual(response["skill_results"][0]["visualization_artifact"]["type"], "line")
        self.assertFalse(response["skill_results"][0]["semantic_info"].get("model_sql_applied", False))
        calls = self.services.task_repository.model_calls("tenant_demo")
        self.assertEqual(len(calls), 2)
        self.assertEqual({item["subject_type"] for item in calls}, {"analysis_planning", "analysis_task"})

    def test_skill_solution_skips_redundant_model_planning_call(self) -> None:
        final_json = json.dumps(
            {
                "analysis_summary": "已按周报 Skill 方案完成证据分析。",
                "conclusions": ["本次结论仅引用已执行数据。"],
                "metric_findings": [],
                "visualization_suggestions": [],
            },
            ensure_ascii=False,
        )
        with patch(
            "backend.platform.intelligent_analysis.engine.call_model_text_completion",
            return_value={
                "status": "connected",
                "model_id": "model_two_stage",
                "used_model": "finance-analysis-v2",
                "request_hash": "5" * 64,
                "response_hash": "6" * 64,
                "response_text": final_json,
                "latency_ms": 10,
            },
        ) as completion:
            response = run_analysis(
                self.services,
                user_id="u_super_admin",
                tenant_id="tenant_demo",
                question="请按周报分析2026年7月各分行放款金额",
                page_context={
                    "selected_model": {"id": "model_two_stage"},
                    "analysis_context_skills": [{"id": "weekly-report"}],
                },
            )

        self.assertEqual(completion.call_count, 1)
        self.assertEqual(response["intelligent_analysis"]["planning_invocation"]["status"], "skipped")
        self.assertEqual(
            response["intelligent_analysis"]["planning_invocation"]["prompt_template_id"],
            "skill_solution.server_plan.v1",
        )

    def test_data_first_policy_queries_before_single_model_conclusion_call(self) -> None:
        final_json = json.dumps(
            {
                "analysis_summary": "数据已先行返回，模型结论随后补充。",
                "conclusions": ["本次结论只基于已执行的查询结果。"],
                "metric_findings": [],
                "visualization_suggestions": [],
            },
            ensure_ascii=False,
        )
        with patch(
            "backend.platform.intelligent_analysis.engine.call_model_text_completion",
            return_value={
                "status": "connected",
                "model_id": "model_two_stage",
                "used_model": "finance-analysis-v2",
                "request_hash": "7" * 64,
                "response_hash": "8" * 64,
                "response_text": final_json,
                "latency_ms": 10,
            },
        ) as completion:
            response = run_analysis(
                self.services,
                user_id="u_super_admin",
                tenant_id="tenant_demo",
                question="2026年7月各分行放款金额排名TOP10",
                page_context={
                    "model_application_module": "intelligent_analysis_reasoning",
                    "model_application_selection": {
                        "integrationId": "model_two_stage",
                        "selectedModelName": "finance-analysis-v2",
                    },
                    "analysis_policy": {"resultDelivery": "data_first"},
                },
            )

        self.assertEqual(completion.call_count, 1)
        self.assertGreater(len(response["skill_results"][0]["data"]), 0)
        self.assertEqual(response["intelligent_analysis"]["planning_invocation"]["status"], "skipped")
        self.assertEqual(
            response["intelligent_analysis"]["planning_invocation"]["prompt_template_id"],
            "data_first.server_plan.v1",
        )
        self.assertEqual(response["intelligent_analysis"]["model_invocation"]["status"], "connected")

    def test_visualization_follow_up_binds_page_filters_model_and_context(self) -> None:
        final_json = json.dumps(
            {
                "analysis_summary": "仅基于当前分行漏斗的重新查询证据生成结论。",
                "conclusions": ["上海分行当前漏斗阶段数据已完成重新查询。"],
                "metric_findings": [],
                "visualization_suggestions": [],
            },
            ensure_ascii=False,
        )
        page_context = {
            "route": "funnel",
            "page_key": "funnel",
            "filters": {"branch_name": "上海分行", "product_line": "经营贷"},
            "dataset_snapshot": {"id": "business_funnel", "version": "2026-08-14T00:00:00Z"},
            "evidence_refs": [{"id": "snap_page_evidence", "type": "operating_snapshot"}],
            "visualization": {"stage_names": ["进件", "完件", "授信", "动支"]},
            "analysis_plan_hint": {
                "dataset_id": "funnel_operation_mart",
                "metrics": ["stage_count"],
                "dimensions": ["branch_name", "product_line", "stage_name", "stage_order", "stat_date"],
                "chart_types": ["column", "table"],
            },
            "model_application_module": "intelligent_analysis_reasoning",
            "analysis_skill": {"id": "page-funnel", "name": "业务漏斗页面追问", "category": "场景"},
            "analysis_context_skills": [{"id": "page-funnel", "name": "业务漏斗页面追问", "category": "场景"}],
            "analysis_policy": {"resultDelivery": "data_first"},
        }
        with patch(
            "backend.platform.intelligent_analysis.engine.call_model_text_completion",
            return_value={
                "status": "connected",
                "model_id": "model_two_stage",
                "used_model": "finance-analysis-v2",
                "response_text": final_json,
            },
        ) as completion:
            response = run_analysis(
                self.services,
                user_id="u_super_admin",
                tenant_id="tenant_demo",
                question="当前漏斗主要断点在哪里",
                page_context=page_context,
            )

        self.assertEqual(completion.call_count, 1)
        plan = response["analysis_plan"]
        self.assertEqual(plan["dataset_id"], "funnel_operation_mart")
        self.assertEqual(plan["metrics"], ["stage_count"])
        self.assertEqual(plan["filters"]["branch_name"], "上海分行")
        self.assertEqual(plan["filters"]["product_line"], "经营贷")
        applied_filters = response["skill_results"][0]["semantic_info"]["applied_filters"]
        self.assertEqual(applied_filters["branch_name"], "上海分行")
        self.assertEqual(applied_filters["product_line"], "经营贷")
        prompt = completion.call_args.args[1]
        self.assertIn("current_page_context_untrusted", prompt)
        self.assertIn("snap_page_evidence", prompt)
        self.assertIn("业务漏斗页面追问", prompt)
        self.assertIn("实际执行证据", prompt)

    def test_surface_context_and_reviewed_memories_are_bounded_into_model_prompt(self) -> None:
        request = IntelligentAnalysisRequest(
            question="继续分析当前图表",
            tenant_id="tenant_demo",
            user_id="u_super_admin",
            analysis_plan={
                "metrics": ["loan_amount"],
                "dimensions": ["branch_name"],
                "memory_refs": [{"memory_id": "mem_reviewed", "memory_type": "analysis_case", "title": "已审核经验", "content": {"rule": "先校验口径"}, "confidence": 0.9}],
            },
            asset_context={
                "matched_intents": [{"id": "intent_branch", "name": "机构排名", "keywords": "分行,排名"}],
                "experiences": [{"id": "exp_branch", "title": "机构比较经验", "steps": ["校验", "比较"]}],
            },
            model={"id": "model_two_stage", "name": "两阶段分析模型"},
            surface_context={
                "route": "supervision",
                "filters": {"branch_name": "上海分行"},
                "selected_data_point": {"targetType": "institution", "targetId": "上海分行"},
                "secret": "must-not-enter-prompt",
            },
        )
        with patch(
            "backend.platform.intelligent_analysis.engine.call_model_text_completion",
            return_value={"status": "failed", "message": "offline"},
        ) as completion:
            IntelligentAnalysisEngine().plan(request)
        prompt = completion.call_args.args[1]
        self.assertIn("mem_reviewed", prompt)
        self.assertIn("intent_branch", prompt)
        self.assertIn("exp_branch", prompt)
        self.assertIn("上海分行", prompt)
        self.assertNotIn("must-not-enter-prompt", prompt)

    def test_runtime_invalid_model_visualization_falls_back_without_failing_analysis(self) -> None:
        planning_json = json.dumps(
            {
                "metrics": ["loan_amount"],
                "dimensions": ["branch_name"],
                "limit": 10,
                "sort_direction": "desc",
                "sql": "SELECT branch_name FROM loan_operation_fact WHERE tenant_id = :tenant_id",
                "data_processing_python": "def process_data(data, context):\n    return {\"rows\": data, \"quality\": {}}\n",
                "visualization_python": "def build_chart(data, context):\n    return {\"type\": \"bar\", \"series\": [{\"name\": key, \"value\": value} for key, value in data.items()]}\n",
                "analysis_approach": ["核对口径"],
                "metric_scenarios": [],
                "visualization_suggestions": [],
            },
            ensure_ascii=False,
        )
        final_json = json.dumps(
            {
                "analysis_summary": "模型图形脚本异常时仍完成分析。",
                "conclusions": ["已使用受治理的默认图形脚本。"],
                "metric_findings": [],
                "visualization_suggestions": [],
            },
            ensure_ascii=False,
        )
        with patch(
            "backend.platform.intelligent_analysis.engine.call_model_text_completion",
            side_effect=[
                {"status": "connected", "response_text": planning_json},
                {"status": "connected", "response_text": final_json},
            ],
        ):
            response = run_analysis(
                self.services,
                user_id="u_super_admin",
                tenant_id="tenant_demo",
                question="2026年7月各分行放款金额排名TOP10",
                page_context={"selected_model": {"id": "model_two_stage"}},
            )

        self.assertEqual(response["status"], "completed")
        self.assertEqual(
            response["skill_results"][0]["visualization_artifact"]["fallback_reason"],
            "model_visualization_runtime_rejected",
        )


if __name__ == "__main__":
    unittest.main()
