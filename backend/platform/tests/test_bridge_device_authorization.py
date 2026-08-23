from __future__ import annotations

import hashlib
import http.client
import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.platform.api.server import create_server
from backend.platform.database import apply_migrations
from backend.platform.integrations.bridge_auth import InMemoryBridgeAuthStore, SQLiteBridgeAuthStore
from backend.platform.security import AuthenticationError

from backend.platform.access.passwords import DEFAULT_ACCOUNT_PASSWORD

TEST_DEVELOPMENT_LOGIN_PASSWORD = DEFAULT_ACCOUNT_PASSWORD


def _request(
    port: int,
    method: str,
    path: str,
    payload: dict | None = None,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, object, list[tuple[str, str]]]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    request_headers = {"Accept": "application/json", **(headers or {})}
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    connection.request(method, path, body=body, headers=request_headers)
    response = connection.getresponse()
    raw = response.read()
    response_headers = response.getheaders()
    content_type = response.getheader("Content-Type") or ""
    parsed: object = json.loads(raw.decode("utf-8")) if "application/json" in content_type else raw.decode("utf-8")
    connection.close()
    return response.status, parsed, response_headers


class BridgeAuthStoreContractTest(unittest.TestCase):
    def test_in_memory_and_sqlite_stores_enforce_expiry_replay_and_revocation(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "bridge.sqlite"
            apply_migrations(db_path)
            stores = (InMemoryBridgeAuthStore(), SQLiteBridgeAuthStore(db_path))
            try:
                for store in stores:
                    with self.subTest(store=type(store).__name__):
                        verifier = "one-time-verifier"
                        started = store.start_enrollment("codex", "Ada Mac", hashlib.sha256(verifier.encode()).hexdigest(), now=100, ttl_seconds=60)
                        self.assertEqual(store.poll_enrollment(started["device_code"], verifier, now=101), {"status": "authorization_pending"})
                        with self.assertRaisesRegex(AuthenticationError, "verifier_invalid"):
                            store.poll_enrollment(started["device_code"], "wrong", now=101)
                        approved = store.approve_enrollment(started["user_code"], "tenant_demo", "u_super_admin", "u_super_admin", now=102)
                        self.assertEqual(approved["status"], "approved")
                        consumed = store.poll_enrollment(started["device_code"], verifier, now=103)
                        self.assertEqual(consumed["status"], "authorized")
                        binding = store.resolve_binding(consumed["token"])
                        self.assertEqual(binding["channel"], "codex")
                        self.assertEqual(binding["tenant_id"], "tenant_demo")
                        with self.assertRaisesRegex(AuthenticationError, "already_consumed"):
                            store.poll_enrollment(started["device_code"], verifier, now=104)
                        self.assertEqual(len(store.list_bindings("tenant_demo", "u_super_admin")), 1)
                        self.assertTrue(store.revoke_binding(binding["binding_id"], "tenant_demo", "u_super_admin", now=105))
                        self.assertIsNone(store.resolve_binding(consumed["token"]))

                        expired = store.start_enrollment("qwork", "Ada PC", hashlib.sha256(verifier.encode()).hexdigest(), now=200, ttl_seconds=60)
                        with self.assertRaisesRegex(AuthenticationError, "expired"):
                            store.enrollment_preview(expired["user_code"], now=260)
            finally:
                for store in stores:
                    store.close()


class BridgeDeviceAuthorizationHTTPTest(unittest.TestCase):
    def setUp(self) -> None:
        self.login_password_environment = patch.dict(
            "os.environ",
            {"SMART_DATA_AGENT_DEVELOPMENT_LOGIN_PASSWORD": TEST_DEVELOPMENT_LOGIN_PASSWORD},
        )
        self.login_password_environment.start()

    def tearDown(self) -> None:
        self.login_password_environment.stop()

    def test_browser_click_authorizes_dynamic_binding_once_and_can_revoke(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/platform.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_address[1]
            try:
                login_status, login, login_headers = _request(
                    port,
                    "POST",
                    "/api/auth/login",
                    {"email": "lina@bank.com", "password": TEST_DEVELOPMENT_LOGIN_PASSWORD},
                )
                self.assertEqual(login_status, 200)
                self.assertIsInstance(login, dict)
                cookies = "; ".join(value.split(";", 1)[0] for name, value in login_headers if name.lower() == "set-cookie")
                self.assertIn("sda_session=", cookies)

                verifier = "browser-click-verifier"
                start_status, started, _ = _request(
                    port,
                    "POST",
                    "/api/integrations/bridge/enrollment/start",
                    {"channel": "qwork", "device_name": "QWork on Ada Mac", "verifier_hash": hashlib.sha256(verifier.encode()).hexdigest()},
                )
                self.assertEqual(start_status, 201)
                self.assertNotIn("token", started)

                verify_status, page, _ = _request(
                    port,
                    "GET",
                    started["verification_api_uri_complete"],
                )
                self.assertEqual(verify_status, 200)
                self.assertIn("允许连接", page)
                self.assertIn("QWork on Ada Mac", page)

                pending_status, pending, _ = _request(
                    port,
                    "POST",
                    "/api/integrations/bridge/enrollment/poll",
                    {"device_code": started["device_code"], "verifier": verifier},
                )
                self.assertEqual(pending_status, 202)
                self.assertEqual(pending["status"], "authorization_pending")

                unauthenticated_status, _, _ = _request(
                    port,
                    "POST",
                    "/api/integrations/bridge/enrollment/approve",
                    {"user_code": started["user_code"]},
                )
                self.assertEqual(unauthenticated_status, 401)

                approve_status, approved, _ = _request(
                    port,
                    "POST",
                    "/api/integrations/bridge/enrollment/approve",
                    {"user_code": started["user_code"]},
                    headers={"Cookie": cookies},
                )
                self.assertEqual(approve_status, 200)
                self.assertTrue(approved["approved"])

                poll_status, authorized, _ = _request(
                    port,
                    "POST",
                    "/api/integrations/bridge/enrollment/poll",
                    {"device_code": started["device_code"], "verifier": verifier},
                )
                self.assertEqual(poll_status, 200)
                self.assertEqual(authorized["status"], "authorized")
                token = authorized["token"]
                self.assertTrue(token)

                context_status, context, _ = _request(
                    port,
                    "GET",
                    "/api/integrations/qwork/context",
                    headers={"Authorization": f"Bearer {token}"},
                )
                self.assertEqual(context_status, 200)
                self.assertEqual(context["channel"], "qwork")

                replay_status, _, _ = _request(
                    port,
                    "POST",
                    "/api/integrations/bridge/enrollment/poll",
                    {"device_code": started["device_code"], "verifier": verifier},
                )
                self.assertEqual(replay_status, 401)

                list_status, listed, _ = _request(
                    port,
                    "GET",
                    "/api/integrations/bridge/bindings",
                    headers={"Cookie": cookies},
                )
                self.assertEqual(list_status, 200)
                self.assertEqual(len(listed["bindings"]), 1)
                binding_id = listed["bindings"][0]["binding_id"]

                revoke_status, revoked, _ = _request(
                    port,
                    "POST",
                    "/api/integrations/bridge/binding/revoke",
                    {"binding_id": binding_id},
                    headers={"Cookie": cookies},
                )
                self.assertEqual(revoke_status, 200)
                self.assertTrue(revoked["revoked"])
                rejected_status, _, _ = _request(
                    port,
                    "GET",
                    "/api/integrations/qwork/context",
                    headers={"Authorization": f"Bearer {token}"},
                )
                self.assertEqual(rejected_status, 401)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
