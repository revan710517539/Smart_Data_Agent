from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.platform.automation.metric_monitor import run_metric_monitor


class _SemanticService:
    def __init__(self, values: tuple[float, float]) -> None:
        self.values = values
        self.requests = []

    def query(self, request):
        self.requests.append(request)
        return SimpleNamespace(
            data=[
                {"stat_week": "2026-07-06", "loan_balance": self.values[0]},
                {"stat_week": "2026-07-13", "loan_balance": self.values[1]},
            ]
        )


class MetricMonitorTest(unittest.TestCase):
    @staticmethod
    def config(threshold: float) -> dict:
        return {
            "selected_metrics": [
                {
                    "optionId": "topic_core_weekly_metrics:loan_balance",
                    "metricName": "在贷余额",
                    "metricCode": "loan_balance",
                    "datasetId": "weekly_core_metrics_mart",
                    "tableId": "topic_core_weekly_metrics",
                    "tableCode": "core_weekly_metrics",
                    "sourceTable": "经营周报三指标",
                    "description": "统计期末剩余未还本金。",
                    "definition": "期末在贷本金余额。",
                    "valueLogic": "sum(loan_balance)",
                    "timeDimension": "stat_week",
                }
            ],
            "analysis_skill": {"id": "topic-descriptive", "category": "主题"},
            "prompt": "对命中异动的指标进行归因分析",
            "model_application_selection": {"integrationId": "model_auto", "selectedModelName": "gpt-test"},
            "anomaly_rule": {
                "comparison": "relative_change",
                "threshold": threshold,
                "direction": "both",
                "match_mode": "any",
            },
        }

    def test_hard_rule_does_not_cross_model_boundary_when_not_triggered(self) -> None:
        services = SimpleNamespace(semantic_service=_SemanticService((100, 105)))
        with patch("backend.platform.api.routes.analysis.run_analysis") as analysis:
            result = run_metric_monitor(
                services,
                tenant_id="tenant_demo",
                user_id="u_admin",
                config=self.config(10),
                trigger_payload={},
                request_id="monitor-not-triggered",
            )
        self.assertFalse(result["triggered"])
        self.assertFalse(result["model_invoked"])
        analysis.assert_not_called()

    def test_trigger_packages_metric_skill_prompt_and_selected_model(self) -> None:
        services = SimpleNamespace(semantic_service=_SemanticService((100, 120)))
        with patch("backend.platform.api.routes.analysis.run_analysis", return_value={"task_id": "task_1", "status": "completed"}) as analysis:
            result = run_metric_monitor(
                services,
                tenant_id="tenant_demo",
                user_id="u_admin",
                config=self.config(10),
                trigger_payload={},
                request_id="monitor-triggered",
            )
        self.assertTrue(result["triggered"])
        self.assertTrue(result["model_invoked"])
        kwargs = analysis.call_args.kwargs
        self.assertIn("经营周报三指标", kwargs["question"])
        self.assertIn("sum(loan_balance)", kwargs["question"])
        self.assertEqual(kwargs["page_context"]["model_application_module"], "automatic_analysis")
        self.assertEqual(kwargs["page_context"]["model_application_selection"]["selectedModelName"], "gpt-test")
        self.assertEqual(kwargs["page_context"]["analysis_skill"]["id"], "topic-descriptive")
        self.assertEqual(kwargs["page_context"]["selected_data_tables"][0]["id"], "topic_core_weekly_metrics")


if __name__ == "__main__":
    unittest.main()
