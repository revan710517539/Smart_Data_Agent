from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backend.platform.api.routes.analysis import _build_asset_context
from backend.platform.bootstrap import build_local_platform
from backend.platform.intelligent_analysis import IntelligentAnalysisEngine
from backend.platform.intelligent_analysis.engine import IntelligentAnalysisRequest
from backend.platform.tests.governed_warehouse import build_governed_test_warehouse


class GovernedAnalysisDataTest(unittest.TestCase):
    def test_default_catalog_contains_no_retired_demo_assets(self) -> None:
        services = build_local_platform()
        self.addCleanup(services.close)
        bundle = services.data_asset_store.list_bundle("tenant_demo")

        self.assertEqual([item for item in bundle["analysis_shortcuts"] if item.get("visible")], [])
        self.assertFalse(any("mock" in str(item.get("id") or "") for item in bundle["topic_tables"]))

    def test_retired_demo_asset_selection_fails_closed(self) -> None:
        services = build_local_platform()
        self.addCleanup(services.close)

        with self.assertRaisesRegex(PermissionError, "selected_data_asset_not_published_or_not_authorized"):
            _build_asset_context(
                services,
                "tenant_demo",
                "分析旧样例数据",
                {"selected_data_tables": [{"id": "topic_mock_loan_funnel"}]},
            )

    def test_governed_warehouse_reconciles_ratio_metrics(self) -> None:
        warehouse = build_governed_test_warehouse()
        result = warehouse.query_matrix(
            "loan_funnel_mock_mart",
            "tenant_demo",
            (
                "completion_order_count",
                "credit_approved_order_count",
                "drawdown_success_order_count",
                "credit_approval_rate",
                "drawdown_rate",
                "approved_amount",
                "drawdown_amount",
                "loan_balance",
                "m1_overdue_rate",
            ),
            ("branch_name",),
            limit=100,
        )

        self.assertEqual(result.full_group_count, 10)
        self.assertGreater(result.totals["completion_order_count"], result.totals["drawdown_success_order_count"])
        self.assertEqual(result.metric_semantics["credit_approval_rate"]["numerator"], "credit_approved_customer_count")
        self.assertEqual(result.metric_semantics["drawdown_rate"]["denominator"], "credit_approved_customer_count")
        self.assertGreater(result.totals["credit_approval_rate"], result.totals["drawdown_rate"])
        snapshot = warehouse.snapshot_info("loan_funnel_mock_mart")
        self.assertTrue(snapshot["immutable"])
        self.assertEqual(len(snapshot["artifact_sha256"]), 64)

    def test_empty_in_filter_never_expands_scope(self) -> None:
        result = build_governed_test_warehouse().query_matrix(
            "loan_operation_mart",
            "tenant_demo",
            ("loan_amount",),
            ("branch_name",),
            filters={"branch_name": {"in": []}},
        )

        self.assertEqual(result.rows, [])
        self.assertEqual(result.totals, {"loan_amount": 0.0})

    def test_model_prompts_preserve_governed_semantics_and_evidence(self) -> None:
        request = IntelligentAnalysisRequest(
            question="按分行分析完件笔数和动支率",
            tenant_id="tenant_demo",
            user_id="u_super_admin",
            analysis_plan={
                "dataset_id": "loan_funnel_mart",
                "metrics": ["completion_order_count", "drawdown_rate"],
                "dimensions": ["branch_name"],
                "metric_definitions": [
                    {"metric_code": "completion_order_count", "metric_name": "完件笔数", "aggregation": "sum", "version": "v1"},
                    {
                        "metric_code": "drawdown_rate", "metric_name": "动支率", "aggregation": "ratio",
                        "numerator": "drawdown_success_customer_count", "denominator": "credit_approved_customer_count",
                        "multiplier": 1, "version": "v1",
                    },
                ],
                "chart_types": ["bar", "table"],
                "limit": 20,
                "sort": {"direction": "desc"},
            },
            asset_context={
                "selected_data_tables": [{
                    "id": "topic_loan_funnel", "name": "贷款申请授信动支主题表",
                    "code": "loan_funnel_mart", "datasetId": "loan_funnel_mart",
                    "csvPath": "Origin_Data/tenant/topic/version/data.csv",
                    "fields": [{
                        "fieldNameEn": "drawdown_success_customer_count", "fieldNameCn": "动支成功人数分子",
                        "type": "integer", "explanation": "动支率分子",
                    }],
                    "sql": "select * from loan_funnel_mart where tenant_id = :tenant_id",
                }],
                "metric_dictionary_definitions": [{
                    "metricId": "M00099", "metricName": "动支率", "definition": "动支成功人数/授信成功人数",
                }],
            },
            skill={"id": "loan-funnel", "name": "贷款漏斗分析", "category": "经营分析", "description": "核对漏斗"},
            files=[{"id": "f1", "name": "补充口径.txt", "type": "text/plain", "contentPreview": "按自然月统计"}],
            model={"id": "model_test", "name": "测试模型"},
            query_result={
                "data": [{"branch_name": "上海分行", "completion_order_count": 10, "drawdown_rate": 0.7}],
                "semantic_info": {"dataset_id": "loan_funnel_mart", "totals": {"completion_order_count": 100, "drawdown_rate": 0.7}},
            },
        )
        failed_completion = {"status": "failed", "error_code": "provider_unavailable", "response_text": ""}

        with patch("backend.platform.intelligent_analysis.engine.call_model_text_completion", return_value=failed_completion) as completion:
            IntelligentAnalysisEngine().run(request)

        self.assertEqual(completion.call_count, 2)
        for call in completion.call_args_list:
            prompt = call.args[1]
            self.assertIn(request.question, prompt)
            self.assertIn("贷款申请授信动支主题表", prompt)
            self.assertIn("Origin_Data/tenant/topic/version/data.csv", prompt)
            self.assertIn("动支成功人数/授信成功人数", prompt)
            self.assertIn("drawdown_success_customer_count", prompt)
            self.assertIn("贷款漏斗分析", prompt)
            self.assertIn("补充口径.txt", prompt)


if __name__ == "__main__":
    unittest.main()
