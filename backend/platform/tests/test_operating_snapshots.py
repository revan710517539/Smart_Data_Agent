from __future__ import annotations

import unittest

from backend.platform.bootstrap import build_local_platform
from backend.platform.tests.governed_warehouse import attach_governed_test_warehouse


class OperatingSnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.services = build_local_platform()
        attach_governed_test_warehouse(self.services)

    def tearDown(self) -> None:
        self.services.close()

    def test_dashboard_snapshot_contains_governed_rows_and_trust_evidence(self) -> None:
        snapshot = self.services.operating_snapshot_service.build("dashboard", "tenant_demo", "u_super_admin")
        self.assertEqual(snapshot["status"], "ready")
        self.assertEqual(snapshot["data_modes"], ["real"])
        self.assertTrue(snapshot["publishable"])
        loan = snapshot["datasets"]["loan_operation"]
        self.assertEqual(loan["status"], "ready")
        self.assertGreater(len(loan["rows"]), 0)
        self.assertTrue(all("loan_amount" in row and "drawdown_rate" in row for row in loan["rows"]))
        self.assertEqual(loan["evidence"]["data_mode"], "real")
        self.assertTrue(loan["evidence"]["publishable"])
        self.assertTrue(loan["evidence"]["policy_enforced_at_source"])
        self.assertTrue(loan["evidence"]["evidence_id"].startswith("snap_"))

    def test_authorized_dashboard_labels_each_tenant_and_does_not_discover_tenants(self) -> None:
        snapshot = self.services.operating_snapshot_service.build_authorized_dashboard(
            ("tenant_demo", "tenant:华兴银行"), "u_super_admin"
        )
        loan = snapshot["datasets"]["loan_operation"]
        self.assertEqual(snapshot["scope"], "authorized_tenants")
        self.assertEqual(snapshot["tenant_ids"], ["tenant_demo", "tenant:华兴银行"])
        self.assertEqual(loan["evidence"]["tenant_count"], 2)
        self.assertTrue(loan["rows"])
        self.assertTrue(all("institution_name" in row for row in loan["rows"]))
        self.assertTrue(all(" · " in str(row.get("branch_name") or "") for row in loan["rows"]))

    def test_funnel_snapshot_uses_governed_dataset(self) -> None:
        snapshot = self.services.operating_snapshot_service.build("business_funnel", "tenant_demo", "u_super_admin")
        funnel = snapshot["datasets"]["funnel_operation"]
        self.assertEqual(snapshot["status"], "ready")
        self.assertTrue(funnel["rows"])
        self.assertTrue(funnel["evidence"]["publishable"])

    def test_unknown_snapshot_view_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            self.services.operating_snapshot_service.build("unknown", "tenant_demo", "u_super_admin")

    def test_weekly_report_snapshot_returns_three_core_metrics_without_model(self) -> None:
        snapshot = self.services.operating_snapshot_service.build("weekly_report", "tenant_demo", "u_super_admin")
        dataset = snapshot["datasets"]["weekly_core_metrics"]
        self.assertEqual(dataset["status"], "ready")
        self.assertGreaterEqual(len(dataset["rows"]), 2)
        self.assertTrue(all(
            {"stat_week", "loan_balance", "loan_amount", "new_balance"}.issubset(row)
            for row in dataset["rows"]
        ))


if __name__ == "__main__":
    unittest.main()
