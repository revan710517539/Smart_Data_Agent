from __future__ import annotations

import unittest

from backend.platform.metrics.versioning import InMemoryMetricVersionStore, MetricVersionService


class MetricVersioningTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MetricVersionService(InMemoryMetricVersionStore())
        self.definition = {
            "metricId": "M001",
            "metricName": "放款金额",
            "metricCode": "loan_amount",
            "datasetId": "loan_fact",
            "aggregationType": "sum",
            "semanticStatus": "draft",
            "semanticVersion": "v1",
            "definition": "实际发放本金",
        }

    def test_four_eyes_publish_diff_and_rollback(self) -> None:
        first = self.service.create("tenant-a", "M001", "author", self.definition)
        review = self.service.review("tenant-a", first["version_id"], "author", "submit")
        self.assertEqual(review["status"], "review")
        with self.assertRaisesRegex(PermissionError, "four_eyes"):
            self.service.review("tenant-a", first["version_id"], "author", "publish")
        published = self.service.review("tenant-a", first["version_id"], "reviewer", "publish", "口径通过")
        self.assertEqual(published["status"], "published")
        second = self.service.create("tenant-a", "M001", "author", {**self.definition, "definition": "修订口径"}, first["version_id"])
        diff = self.service.diff("tenant-a", "M001", first["version_id"], second["version_id"])
        self.assertEqual(diff["changed_count"], 1)
        rollback = self.service.rollback("tenant-a", "M001", first["version_id"], "author")
        self.assertEqual(rollback["status"], "draft")
        self.assertEqual(rollback["rollback_of"], first["version_id"])

    def test_invalid_state_and_cross_tenant_fail_closed(self) -> None:
        version = self.service.create("tenant-a", "M001", "author", self.definition)
        with self.assertRaisesRegex(ValueError, "review_state"):
            self.service.review("tenant-a", version["version_id"], "reviewer", "publish")
        with self.assertRaisesRegex(KeyError, "not_found"):
            self.service.review("tenant-b", version["version_id"], "reviewer", "submit")


if __name__ == "__main__":
    unittest.main()
