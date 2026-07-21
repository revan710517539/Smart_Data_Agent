import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.platform.application import SQLiteApplicationStore
from backend.platform.audit import SQLiteAuditEventStore
from backend.platform.database import apply_migrations


class AuditSecurityTest(unittest.TestCase):
    def test_audit_and_action_history_redact_secrets_and_large_business_content(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "platform.sqlite"
            apply_migrations(db_path)
            audit = SQLiteAuditEventStore(db_path, initialize=False)
            application = SQLiteApplicationStore(db_path, initialize=False)
            try:
                event = audit.write(
                    tenant_id="tenant_demo",
                    actor_user_id="u_admin",
                    action="security.redaction_test",
                    target_type="test",
                    detail={
                        "password": "raw-password-value",
                        "apiKey": "raw-api-key-value",
                        "contentPreview": "customer-sensitive-content" * 100,
                        "safe_id": "dataset_123",
                    },
                    ip_address="10.12.34.56",
                )
                application.run_action(
                    "tenant_demo",
                    "dashboard",
                    "select_bank",
                    payload={
                        "selectedBank": "杭州分行",
                        "access_token": "raw-action-token",
                        "content": "raw-action-content" * 100,
                    },
                    actor_user_id="u_admin",
                )
            finally:
                audit.close()
                application.close()

            self.assertEqual(event["detail"]["password"], "[REDACTED]")
            self.assertEqual(event["detail"]["apiKey"], "[REDACTED]")
            self.assertTrue(event["detail"]["contentPreview"]["redacted"])
            self.assertEqual(event["detail"]["safe_id"], "dataset_123")
            self.assertEqual(event["ip_address"], "10.12.34.*")

            connection = sqlite3.connect(db_path)
            try:
                detail = json.loads(connection.execute("SELECT detail FROM platform_audit_events").fetchone()[0])
                action_payload = json.loads(connection.execute("SELECT payload FROM platform_application_actions").fetchone()[0])
            finally:
                connection.close()
            self.assertEqual(detail["password"], "[REDACTED]")
            self.assertEqual(action_payload["access_token"], "[REDACTED]")
            self.assertTrue(action_payload["content"]["redacted"])

            database_bytes = db_path.read_bytes()
            self.assertNotIn(b"raw-password-value", database_bytes)
            self.assertNotIn(b"raw-api-key-value", database_bytes)
            self.assertNotIn(b"raw-action-token", database_bytes)


if __name__ == "__main__":
    unittest.main()
