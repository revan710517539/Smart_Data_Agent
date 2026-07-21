from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.platform.database import apply_migrations
from backend.platform.governance import SQLiteCapabilityApprovalStore, approval_input_hash


class CapabilityApprovalTest(unittest.TestCase):
    def test_approval_is_four_eyes_hash_bound_one_time_and_durable(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "platform.sqlite"
            apply_migrations(db_path)
            inputs = {"dataset_id": "loan_operation_mart", "metric": "loan_amount"}
            input_hash = approval_input_hash(inputs)
            store = SQLiteCapabilityApprovalStore(db_path)
            request = store.request(
                "tenant_demo",
                "mcp",
                "database.query",
                "execute",
                input_hash,
                "u_requester",
                "Need a governed query",
            )
            with self.assertRaises(PermissionError):
                store.review(
                    "tenant_demo", request["approval_id"], "u_requester", "approved"
                )
            approved = store.review(
                "tenant_demo", request["approval_id"], "u_reviewer", "approved"
            )
            self.assertEqual(approved["status"], "approved")
            store.close()

            reopened = SQLiteCapabilityApprovalStore(db_path)
            try:
                with self.assertRaisesRegex(PermissionError, "scope_mismatch"):
                    reopened.consume(
                        request["approval_id"],
                        tenant_id="tenant_demo",
                        requested_by="u_requester",
                        subject_type="mcp",
                        subject_id="database.query",
                        action="execute",
                        input_hash=approval_input_hash({"dataset_id": "another_dataset"}),
                    )
                consumed = reopened.consume(
                    request["approval_id"],
                    tenant_id="tenant_demo",
                    requested_by="u_requester",
                    subject_type="mcp",
                    subject_id="database.query",
                    action="execute",
                    input_hash=input_hash,
                )
                self.assertEqual(consumed["status"], "consumed")
                with self.assertRaisesRegex(PermissionError, "not_approved"):
                    reopened.consume(
                        request["approval_id"],
                        tenant_id="tenant_demo",
                        requested_by="u_requester",
                        subject_type="mcp",
                        subject_id="database.query",
                        action="execute",
                        input_hash=input_hash,
                    )
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
