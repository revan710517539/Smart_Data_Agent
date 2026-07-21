from __future__ import annotations

import unittest

from backend.platform.bootstrap import build_local_platform


class OperatingSnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.services = build_local_platform()

    def tearDown(self) -> None:
        self.services.close()

    def test_dashboard_snapshot_contains_governed_rows_and_explicit_mock_gate(self) -> None:
        snapshot = self.services.operating_snapshot_service.build("dashboard", "tenant_demo", "u_admin")
        self.assertEqual(snapshot["status"], "ready")
        self.assertEqual(snapshot["data_modes"], ["mock"])
        self.assertFalse(snapshot["publishable"])
        loan = snapshot["datasets"]["loan_operation"]
        self.assertEqual(loan["status"], "ready")
        self.assertGreater(len(loan["rows"]), 0)
        self.assertTrue(all("loan_amount" in row and "drawdown_rate" in row for row in loan["rows"]))
        self.assertEqual(loan["evidence"]["data_mode"], "mock")
        self.assertFalse(loan["evidence"]["publishable"])
        self.assertTrue(loan["evidence"]["policy_enforced_at_source"])
        self.assertTrue(loan["evidence"]["evidence_id"].startswith("snap_"))

    def test_missing_funnel_dataset_returns_unavailable_not_fabricated_stages(self) -> None:
        snapshot = self.services.operating_snapshot_service.build("business_funnel", "tenant_demo", "u_admin")
        funnel = snapshot["datasets"]["funnel_operation"]
        self.assertEqual(snapshot["status"], "unavailable")
        self.assertEqual(funnel["rows"], [])
        self.assertEqual(funnel["error_code"], "dataset_unavailable_or_forbidden")
        self.assertFalse(funnel["evidence"]["publishable"])

    def test_unknown_snapshot_view_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            self.services.operating_snapshot_service.build("unknown", "tenant_demo", "u_admin")

    def test_weekly_report_snapshot_returns_three_core_metrics_without_model(self) -> None:
        snapshot = self.services.operating_snapshot_service.build("weekly_report", "tenant_demo", "u_admin")
        dataset = snapshot["datasets"]["weekly_core_metrics"]
        self.assertEqual(dataset["status"], "ready")
        self.assertGreaterEqual(len(dataset["rows"]), 2)
        self.assertTrue(all(
            {"stat_week", "loan_balance", "loan_amount", "new_balance"}.issubset(row)
            for row in dataset["rows"]
        ))


if __name__ == "__main__":
    unittest.main()
