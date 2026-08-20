import json
import http.client
import sqlite3
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.platform.application import SQLiteApplicationStore
from backend.platform.audit import SQLiteAuditEventStore
from backend.platform.api.server import create_server
from backend.platform.database import apply_migrations


class AuditSecurityTest(unittest.TestCase):
    def test_audit_logs_http_endpoint_returns_twenty_row_pages(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, str(Path(tmpdir) / "api.sqlite"))
            for index in range(25):
                server.services.audit_store.write(
                    tenant_id="tenant_demo",
                    actor_user_id="u_super_admin",
                    action=f"audit.http_page.{index}",
                    target_type="test",
                )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
                connection.request(
                    "GET",
                    "/api/audit-logs?tenant_id=tenant_demo&user_id=u_super_admin&limit=20&offset=20",
                )
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["limit"], 20)
        self.assertEqual(payload["offset"], 20)
        self.assertGreaterEqual(payload["total"], 25)
        self.assertLessEqual(len(payload["logs"]), 20)
        self.assertTrue(all(item["actor_user_id"] == "u_super_admin" for item in payload["logs"]))
        self.assertTrue(all(item["actor_name"] == "胥京波" for item in payload["logs"]))
        self.assertIn("since", payload)

    def test_audit_actor_name_survives_missing_user_profile(self):
        from backend.platform.api.routes.audit import _with_actor_name

        class _BrokenStore:
            def get_profile(self, user_id):
                raise KeyError(user_id)

        handler = type("Handler", (), {
            "services": type("Services", (), {
                "access_service": type("Access", (), {"user_store": _BrokenStore()})(),
            })(),
        })()
        named = _with_actor_name(handler, {"event_id": "e1", "actor_user_id": "u_missing"})
        self.assertEqual(named["actor_name"], "未知用户")

    def test_audit_store_returns_stable_twenty_row_pages(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "platform.sqlite"
            audit = SQLiteAuditEventStore(db_path)
            try:
                for index in range(25):
                    audit.write(
                        tenant_id="tenant_demo",
                        actor_user_id="u_admin",
                        action=f"audit.page.{index}",
                        target_type="test",
                    )
                first_page = audit.list_for_tenants(["tenant_demo"], limit=20, offset=0)
                second_page = audit.list_for_tenants(["tenant_demo"], limit=20, offset=20)
                total = audit.count_for_tenants(["tenant_demo"])
            finally:
                audit.close()

        self.assertEqual(total, 25)
        self.assertEqual(len(first_page), 20)
        self.assertEqual(len(second_page), 5)
        self.assertFalse({item["event_id"] for item in first_page} & {item["event_id"] for item in second_page})

    def test_audit_store_filters_events_older_than_seven_days(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "platform.sqlite"
            audit = SQLiteAuditEventStore(db_path)
            try:
                recent = audit.write(tenant_id="tenant_demo", actor_user_id="u_admin", action="audit.recent", target_type="test")
                stale = audit.write(tenant_id="tenant_demo", actor_user_id="u_admin", action="audit.stale", target_type="test")
                audit._conn.execute(
                    "UPDATE platform_audit_events SET created_at = ? WHERE event_id = ?",
                    ("2020-01-01T00:00:00+00:00", stale["event_id"]),
                )
                audit._conn.commit()
                since = "2026-08-12T00:00:00+00:00"
                listed = audit.list_for_tenants(["tenant_demo"], since=since)
                total = audit.count_for_tenants(["tenant_demo"], since=since)
            finally:
                audit.close()

        self.assertEqual(total, 1)
        self.assertEqual([item["event_id"] for item in listed], [recent["event_id"]])

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
