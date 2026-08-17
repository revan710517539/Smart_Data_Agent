from __future__ import annotations

import unittest

from backend.platform.api.routes.metrics import _duplicate_metric_names


class MetricDictionaryImportTest(unittest.TestCase):
    def test_duplicate_names_include_existing_and_same_workbook_names_in_source_order(self) -> None:
        rows = [
            {"metricName": "新增余额"},
            {"metricName": "动支率"},
            {"metricName": "新增余额"},
            {"metricName": "在贷余额"},
        ]

        self.assertEqual(
            _duplicate_metric_names(rows, {"动支率"}),
            ["新增余额", "动支率"],
        )

    def test_unique_workbook_names_are_accepted(self) -> None:
        self.assertEqual(
            _duplicate_metric_names([{"metricName": "新增余额"}, {"metricName": "动支率"}], set()),
            [],
        )


if __name__ == "__main__":
    unittest.main()
