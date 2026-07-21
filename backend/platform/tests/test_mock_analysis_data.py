from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
import unittest
from unittest.mock import patch

from backend.platform.api.routes.analysis import run_analysis
from backend.platform.bootstrap import build_local_platform
from backend.platform.data_access import JSONDataWarehouse
from backend.platform.intelligent_analysis import IntelligentAnalysisEngine
from backend.platform.intelligent_analysis.engine import IntelligentAnalysisRequest


ROOT = Path(__file__).resolve().parents[3]
MOCK = ROOT / "data" / "mock"


def _rows(name: str) -> list[dict[str, str]]:
    with (MOCK / name).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class MockAnalysisDataTest(unittest.TestCase):
    def test_seven_configured_shortcuts_execute_their_bound_mock_datasets(self) -> None:
        services = build_local_platform()
        self.addCleanup(services.close)
        services.system_config_store.upsert_model(
            "tenant_demo",
            {
                "id": "model_shortcut_route", "name": "快捷分析模型", "modelName": "中转站",
                "key": "https://example.local/v1", "value": "shortcut-test-key",
                "availableModels": ["shortcut-model"], "enabledModels": ["shortcut-model"],
                "applicationModule": "intelligent_analysis_reasoning",
                "testStatus": "connected", "status": "available",
            },
            updated_by="u_admin",
        )
        bundle = services.data_asset_store.list_bundle("tenant_demo")
        shortcuts = sorted(
            (item for item in bundle["analysis_shortcuts"] if item.get("visible")),
            key=lambda item: int(item.get("sortOrder") or 0),
        )
        topic_by_id = {item["id"]: item for item in bundle["topic_tables"]}
        self.assertEqual(len(shortcuts), 7)
        failed_completion = {"status": "failed", "error_code": "test_provider_offline", "response_text": ""}
        with patch("backend.platform.intelligent_analysis.engine.call_model_text_completion", return_value=failed_completion):
            for shortcut in shortcuts:
                table_id = shortcut["tableIds"][0]
                result = run_analysis(
                    services,
                    user_id="u_admin",
                    tenant_id="tenant_demo",
                    question=shortcut["query"],
                    page_context={
                        "model_application_module": "intelligent_analysis_reasoning",
                        "selected_data_tables": [{"id": table_id}],
                    },
                )
                self.assertEqual(result["analysis_plan"]["dataset_id"], topic_by_id[table_id]["datasetId"])
                self.assertTrue(result["skill_results"][0]["data"])

    def test_model_processing_script_cannot_drop_governed_metrics(self) -> None:
        services = build_local_platform()
        self.addCleanup(services.close)
        services.system_config_store.upsert_model(
            "tenant_demo",
            {
                "id": "model_integrity_test", "name": "完整性测试模型", "modelName": "中转站",
                "key": "https://example.local/v1", "value": "real-test-key",
                "availableModels": ["integrity-model"], "enabledModels": ["integrity-model"], "status": "available",
            },
            updated_by="u_admin",
        )
        bad_processing = '''def process_data(data, context):
    rows = [{"branch_name": row.get("branch_name", "")} for row in data]
    return {"rows": rows, "quality": {"claimed": "ok"}}
'''
        visualization = '''def build_chart(data, context):
    return {"type": "bar", "title": "完整性测试", "x": context.get("x", "branch_name"), "y": context.get("y", "metric_value"), "series": data, "table_rows": data}
'''
        planning = json.dumps({
            "metrics": ["completion_order_count", "drawdown_rate"], "dimensions": ["branch_name"],
            "limit": 20, "sort_direction": "desc",
            "sql": "select * from mock_loan_transaction_order where tenant_id = :tenant_id",
            "data_processing_python": bad_processing, "visualization_python": visualization,
            "analysis_approach": ["核对漏斗"], "metric_scenarios": [],
            "visualization_suggestions": [{"type": "bar", "title": "漏斗", "dimension": "branch_name", "metric": "completion_order_count", "purpose": "比较"}],
        }, ensure_ascii=False)
        final = json.dumps({
            "analysis_summary": "核心结论：使用实际证据。数据证据：见返回行。原因边界：仅限模拟数据。经营建议：复核。风险提示：不得外推。后续动作：持续跟踪。",
            "conclusions": ["使用实际证据。"], "metric_findings": [], "visualization_suggestions": [],
            "conclusion_coverage": {},
        }, ensure_ascii=False)
        completions = [
            {"status": "connected", "model_id": "model_integrity_test", "used_model": "integrity-model", "response_text": planning},
            {"status": "connected", "model_id": "model_integrity_test", "used_model": "integrity-model", "response_text": final},
        ]
        with patch("backend.platform.intelligent_analysis.engine.call_model_text_completion", side_effect=completions):
            result = run_analysis(
                services,
                user_id="u_admin",
                tenant_id="tenant_demo",
                question="按分行分析完件笔数和动支率",
                page_context={"selected_data_tables": [{"id": "topic_mock_loan_funnel"}], "selected_model": {"id": "model_integrity_test"}},
            )
        output = result["skill_results"][0]
        self.assertEqual(output["data_processing_artifact"]["fallback_reason"], "model_data_processing_integrity_rejected")
        self.assertTrue(output["data_processing_artifact"]["required_fields_preserved"])
        self.assertTrue(all("completion_order_count" in row and "drawdown_rate" in row for row in output["data"]))
        self.assertTrue(result["review"]["checks"]["python_required_fields_preserved"])

    def test_model_prompts_receive_question_table_semantics_metrics_file_and_skill(self) -> None:
        request = IntelligentAnalysisRequest(
            question="按分行分析完件笔数和动支率",
            tenant_id="tenant_demo",
            user_id="u_admin",
            analysis_plan={
                "dataset_id": "loan_funnel_mock_mart",
                "metrics": ["completion_order_count", "drawdown_rate"],
                "dimensions": ["branch_name"],
                "metric_definitions": [
                    {"metric_code": "completion_order_count", "metric_name": "完件笔数", "aggregation": "sum", "version": "mock-v1"},
                    {"metric_code": "drawdown_rate", "metric_name": "动支率（人数）", "aggregation": "ratio", "numerator": "drawdown_success_customer_count", "denominator": "credit_approved_customer_count", "multiplier": 1, "version": "mock-v1"},
                ],
                "chart_types": ["bar", "table"],
                "limit": 20,
                "sort": {"direction": "desc"},
            },
            asset_context={
                "selected_data_tables": [{
                    "id": "topic_mock_loan_funnel", "name": "模拟贷款申请授信动支主题表（100条）",
                    "code": "loan_funnel_mock_mart", "datasetId": "loan_funnel_mock_mart",
                    "csvPath": "data/mock/loan_transaction_order_100.csv",
                    "fields": [{"fieldNameEn": "drawdown_success_customer_count", "fieldNameCn": "动支成功人数分子", "type": "integer", "explanation": "动支率分子"}],
                    "sql": "select * from mock_loan_transaction_order where tenant_id = :tenant_id",
                }],
                "metric_dictionary_definitions": [{"metricId": "M00099", "metricName": "动支率（人数）", "definition": "动支成功人数/授信成功人数"}],
            },
            skill={"id": "loan-funnel", "name": "贷款漏斗分析", "category": "经营分析", "description": "核对漏斗"},
            files=[{"id": "f1", "name": "补充口径.txt", "type": "text/plain", "contentPreview": "按自然月统计"}],
            model={"id": "model_test", "name": "测试模型"},
            query_result={"data": [{"branch_name": "上海分行", "completion_order_count": 10, "drawdown_rate": 0.7}], "semantic_info": {"dataset_id": "loan_funnel_mock_mart", "totals": {"completion_order_count": 100, "drawdown_rate": 0.722222}}},
        )
        failed_completion = {"status": "failed", "error_code": "provider_unavailable", "response_text": ""}
        with patch("backend.platform.intelligent_analysis.engine.call_model_text_completion", return_value=failed_completion) as completion:
            IntelligentAnalysisEngine().run(request)
        self.assertEqual(completion.call_count, 2)
        for prompt in (completion.call_args_list[0].args[1], completion.call_args_list[1].args[1]):
            self.assertIn(request.question, prompt)
            self.assertIn("模拟贷款申请授信动支主题表（100条）", prompt)
            self.assertIn("data/mock/loan_transaction_order_100.csv", prompt)
            self.assertIn("动支成功人数/授信成功人数", prompt)
            self.assertIn("drawdown_success_customer_count", prompt)
            self.assertIn("贷款漏斗分析", prompt)
            self.assertIn("补充口径.txt", prompt)

    def test_relational_csv_fixtures_are_exact_and_consistent(self) -> None:
        institutions = _rows("institution_master_100.csv")
        customers = _rows("customer_master_100.csv")
        orders = _rows("loan_transaction_order_100.csv")
        self.assertEqual((len(institutions), len(customers), len(orders)), (100, 100, 100))
        self.assertEqual(len({row["institution_id"] for row in institutions}), 100)
        self.assertEqual(len({row["customer_id"] for row in customers}), 100)
        self.assertEqual(len({row["order_id"] for row in orders}), 100)
        institution_ids = {row["institution_id"] for row in institutions}
        customer_by_id = {row["customer_id"]: row for row in customers}
        self.assertTrue(all(row["institution_id"] in institution_ids for row in customers))
        for order in orders:
            customer = customer_by_id[order["customer_id"]]
            self.assertEqual(order["institution_id"], customer["institution_id"])
            self.assertLessEqual(float(order["drawdown_amount"]), float(order["approved_amount"]))
            self.assertLessEqual(float(order["approved_amount"]), float(order["application_amount"]))
            self.assertLessEqual(float(order["m1_overdue_balance"]), float(order["loan_balance"]))
            self.assertLessEqual(float(order["loan_balance"]), float(order["drawdown_amount"]))
            lifecycle_dates = [
                date.fromisoformat(order[field])
                for field in ("application_date", "completion_date", "decision_date", "drawdown_application_date", "drawdown_date")
                if order[field]
            ]
            self.assertEqual(lifecycle_dates, sorted(lifecycle_dates))

    def test_csv_warehouse_reconciles_governed_ratio_metrics(self) -> None:
        quality = json.loads((MOCK / "mock_data_quality_report.json").read_text(encoding="utf-8"))
        warehouse = JSONDataWarehouse()
        result = warehouse.query_matrix(
            "loan_funnel_mock_mart",
            "tenant_demo",
            ("completion_order_count", "credit_approved_order_count", "drawdown_success_order_count", "credit_approval_rate", "drawdown_rate", "approved_amount", "drawdown_amount", "loan_balance", "m1_overdue_rate"),
            ("branch_name",),
            limit=100,
        )
        expected = quality["metric_reconciliation"]
        for metric in result.metrics:
            self.assertAlmostEqual(result.totals[metric], expected[metric], places=6)
        self.assertEqual(result.metric_semantics["credit_approval_rate"]["numerator"], "credit_approved_customer_count")
        self.assertEqual(result.metric_semantics["drawdown_rate"]["denominator"], "credit_approved_customer_count")
        snapshot = warehouse.snapshot_info("loan_funnel_mock_mart")
        self.assertEqual(len(snapshot["artifact_sha256"]), 64)
        self.assertTrue(snapshot["immutable"])

    def test_selected_topic_drives_metric_dictionary_python_and_visualization(self) -> None:
        services = build_local_platform()
        self.addCleanup(services.close)
        result = run_analysis(
            services,
            user_id="u_admin",
            tenant_id="tenant_demo",
            question="按分行分析完件笔数、授信通过率和动支率",
            page_context={
                "selected_data_tables": [{"id": "topic_mock_loan_funnel"}],
                "analysis_skill": {"id": "loan-funnel", "name": "贷款漏斗分析", "category": "经营分析", "description": "核对完件、授信、动支"},
                "files": [{"id": "f1", "name": "补充口径.txt", "type": "text/plain", "contentPreview": "按自然月和分行统计"}],
            },
        )
        self.assertEqual(result["analysis_plan"]["dataset_id"], "loan_funnel_mock_mart")
        self.assertEqual(result["analysis_plan"]["metrics"], ["completion_order_count", "credit_approval_rate", "drawdown_rate"])
        definitions = result["analysis_plan"]["metric_definitions"]
        self.assertEqual([item["metric_name"] for item in definitions], ["完件笔数", "授信通过率（人数）", "动支率（人数）"])
        dictionary_names = [item["metricName"] for item in result["asset_context"]["metric_dictionary_definitions"]]
        self.assertEqual(dictionary_names, ["完件笔数", "授信通过率（人数）", "动支率（人数）"])
        output = result["skill_results"][0]
        self.assertEqual(output["data_processing_artifact"]["input_row_count"], output["data_processing_artifact"]["output_row_count"])
        self.assertTrue(output["data_processing_artifact"]["metric_definitions_bound"])
        self.assertIn("def process_data(data, context):", output["data_processing_python_script"])
        self.assertIn("def build_chart(data, context):", output["python_script"])
        self.assertTrue(output["visualization_artifact"]["series"])
        self.assertTrue(result["review"]["checks"]["python_data_processing_ready"])
        self.assertTrue(result["review"]["checks"]["python_visualization_ready"])
        coverage = output["intelligent_analysis"]["conclusion_coverage"]
        self.assertEqual(set(coverage["extrema_covered_metrics"]), set(result["analysis_plan"]["metrics"]))
        self.assertEqual(set(coverage["anomaly_checked_metrics"]), set(result["analysis_plan"]["metrics"]))
        self.assertEqual(set(coverage["definition_bound_metrics"]), set(result["analysis_plan"]["metrics"]))
        self.assertTrue(coverage["all_groups_returned"])
        conclusions = "\n".join(output["intelligent_analysis"]["possible_conclusions"])
        self.assertIn("最低为", conclusions)
        self.assertIn("零值分组", conclusions)
        self.assertIn("越界或负值异常分组", conclusions)
        self.assertIn("drawdown_success_customer_count/credit_approved_customer_count", conclusions)
        self.assertTrue(result["review"]["checks"]["conclusion_coverage_complete"])

    def test_funnel_count_terms_bind_and_reconcile_governed_count_metrics(self) -> None:
        services = build_local_platform()
        self.addCleanup(services.close)
        result = run_analysis(
            services,
            user_id="u_admin",
            tenant_id="tenant_demo",
            question="按分行核对总完件100笔、授信通过72笔、动支成功52笔，同时分析授信通过率和动支率",
            page_context={"selected_data_tables": [{"id": "topic_mock_loan_funnel"}]},
        )
        self.assertEqual(
            result["analysis_plan"]["metrics"],
            [
                "completion_order_count",
                "credit_approved_order_count",
                "drawdown_success_order_count",
                "credit_approval_rate",
                "drawdown_rate",
            ],
        )
        totals = result["skill_results"][0]["semantic_info"]["totals"]
        self.assertEqual(totals["completion_order_count"], 100)
        self.assertEqual(totals["credit_approved_order_count"], 72)
        self.assertEqual(totals["drawdown_success_order_count"], 52)
        self.assertAlmostEqual(totals["credit_approval_rate"], 0.72, places=6)
        self.assertAlmostEqual(totals["drawdown_rate"], 0.722222, places=6)
        self.assertEqual(result["analysis_plan"]["dimensions"], ["branch_name"])
        self.assertTrue(result["review"]["checks"]["conclusion_coverage_complete"])
        narrowed = services.workflow._apply_model_planning(
            result["analysis_plan"],
            {"metrics": ["credit_approval_rate"], "dimensions": [], "limit": 10},
        )
        self.assertEqual(set(narrowed["metrics"]), set(result["analysis_plan"]["metrics"]))
        self.assertEqual(narrowed["dimensions"], ["branch_name"])


if __name__ == "__main__":
    unittest.main()
