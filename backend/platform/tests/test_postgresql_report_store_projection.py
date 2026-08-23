from __future__ import annotations

import unittest

import json

from backend.platform.reports.postgresql_store import PostgreSQLReportStore, _PRESENTATION_CONFIG_TAG_PREFIX
from backend.platform.reports.store import _normalize_analysis_result


class PostgreSQLReportStoreProjectionTests(unittest.TestCase):
    def test_saved_analysis_row_restores_weekly_report_marker(self) -> None:
        row = {
            "id": "analysis_saved_1",
            "title": "经营趋势",
            "query": "分析经营趋势",
            "response_snapshot": {"summary": "趋势稳定"},
            "saved_at": "2026-08-16T08:00:00Z",
            "analysis_task_id": "analysis_task_1",
            "owner_user_id": "u_admin",
            "visibility": "private",
            "tags": [
                "system:weekly-report",
                "system:weekly-report-saved-at:2026-08-16T08:01:00+00:00",
            ],
        }

        result = PostgreSQLReportStore._saved_analysis_row(row)

        self.assertTrue(result["weeklyReportEligible"])
        self.assertEqual(result["weeklyReportSavedAt"], "2026-08-16T08:01:00+00:00")

    def test_saved_analysis_row_defaults_to_not_in_weekly_report(self) -> None:
        row = {
            "id": "analysis_saved_2",
            "title": "经营趋势",
            "query": "分析经营趋势",
            "response_snapshot": {},
            "saved_at": "2026-08-16T08:00:00Z",
            "analysis_task_id": "analysis_task_2",
            "owner_user_id": "u_admin",
            "visibility": "private",
            "tags": [],
        }

        result = PostgreSQLReportStore._saved_analysis_row(row)

        self.assertFalse(result["weeklyReportEligible"])
        self.assertEqual(result["weeklyReportSavedAt"], "")

    def test_saved_analysis_visualizations_are_bounded_and_restored_from_presentation_tag(self) -> None:
        visualizations = [{
            "id": "primary",
            "key": "primary",
            "title": "主分析视图 · 条形图",
            "type": "bar",
            "config": {
                "metricFields": ["amount", "amount"],
                "dimensionFields": ["branch"],
                "filters": {"branch": ["A", "B"]},
                "filterGroups": [{
                    "id": "group-1",
                    "rules": [{"id": "rule-1", "field": "branch", "operator": "in", "values": ["A"]}],
                }],
                "sumFilteredRows": True,
                "comboLineFields": ["amount"],
            },
        }]
        row = {
            "id": "analysis_saved_visual",
            "title": "经营趋势",
            "query": "分析经营趋势",
            "response_snapshot": {},
            "saved_at": "2026-08-16T08:00:00Z",
            "analysis_task_id": "analysis_task_2",
            "owner_user_id": "u_admin",
            "visibility": "private",
            "tags": [_PRESENTATION_CONFIG_TAG_PREFIX + json.dumps(visualizations, ensure_ascii=False)],
        }

        result = PostgreSQLReportStore._saved_analysis_row(row)

        self.assertEqual(result["visualizations"][0]["type"], "bar")
        self.assertEqual(result["visualizations"][0]["config"]["metricFields"], ["amount"])
        self.assertEqual(result["visualizations"][0]["config"]["filterGroups"][0]["rules"][0]["values"], ["A"])

    def test_invalid_saved_analysis_visualization_is_rejected_before_persistence(self) -> None:
        with self.assertRaisesRegex(ValueError, "saved_analysis_visualizations_invalid"):
            _normalize_analysis_result({
                "id": "invalid_visual",
                "title": "无效图表",
                "analysisTaskId": "task_1",
                "visualizations": [{"id": "visual-1", "type": "unsupported"}],
            })

    def test_stacked_bar_uses_the_frontend_contract_value(self) -> None:
        normalized = _normalize_analysis_result({
            "id": "stacked_visual",
            "title": "堆叠图",
            "analysisTaskId": "task_1",
            "visualizations": [{"id": "visual-1", "type": "stacked_bar"}],
        })

        self.assertEqual(normalized["visualizations"][0]["type"], "stacked_bar")

    def test_text_visualization_and_note_aliases_are_persisted(self) -> None:
        normalized = _normalize_analysis_result({
            "id": "text_visual",
            "title": "文本总结",
            "analysisTaskId": "task_1",
            "visualizations": [{
                "id": "primary",
                "key": "primary",
                "title": "文本总结",
                "type": "text",
                "config": {
                    "metricFields": [],
                    "dimensionFields": [],
                    "filters": {},
                    "filterGroups": [],
                    "sumFilteredRows": False,
                    "comboLineFields": [],
                    "noteTitle": "结论",
                    "noteBody": "本周放款回升。",
                    "noteTitleHidden": False,
                    "noteItems": [{"id": "p1", "type": "paragraph", "text": "本周放款回升。"}],
                    "layoutSpan": 2,
                },
            }, {
                "id": "secondary",
                "type": "textbox",
            }],
        })

        self.assertEqual(normalized["visualizations"][0]["type"], "text")
        self.assertEqual(normalized["visualizations"][0]["config"]["noteBody"], "本周放款回升。")
        self.assertEqual(normalized["visualizations"][0]["config"]["layoutSpan"], 2)
        self.assertEqual(normalized["visualizations"][1]["type"], "text")

    def test_pie_alias_is_normalized_to_donut(self) -> None:
        normalized = _normalize_analysis_result({
            "id": "pie_visual",
            "title": "结构图",
            "analysisTaskId": "task_1",
            "visualizations": [{"id": "visual-1", "type": "pie"}],
        })

        self.assertEqual(normalized["visualizations"][0]["type"], "donut")


if __name__ == "__main__":
    unittest.main()
