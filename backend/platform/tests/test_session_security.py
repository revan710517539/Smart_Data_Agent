from __future__ import annotations

import http.client
import json
import threading
from http.cookies import SimpleCookie
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.platform.access.passwords import DEFAULT_ACCOUNT_PASSWORD
from backend.platform.api.server import create_server
from backend.platform.database import apply_migrations
from backend.platform.security import AuthenticationError, InMemorySessionStore, SQLiteSessionStore


def _cookie_jar(response: http.client.HTTPResponse) -> dict[str, str]:
    values: dict[str, str] = {}
    for name, value in response.getheaders():
        if name.lower() != "set-cookie":
            continue
        parsed = SimpleCookie()
        parsed.load(value)
        for cookie_name, morsel in parsed.items():
            if morsel["max-age"] == "0":
                values.pop(cookie_name, None)
            else:
                values[cookie_name] = morsel.value
    return values


def _cookie_header(jar: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in jar.items())


class SessionSecurityTest(unittest.TestCase):
    def test_development_email_login_rejects_empty_and_wrong_passwords(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
                connection.request(
                    "POST",
                    "/api/auth/login",
                    body=json.dumps({"email": "lina@bank.com", "password": ""}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(response.status, 400)
        self.assertEqual(payload["error"], "invalid_request")
        self.assertEqual(payload["message"], "账号或密码不正确，请确认后重试。")

    def test_development_email_login_requires_the_configured_password(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                wrong_password = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                wrong_password.request(
                    "POST",
                    "/api/auth/login",
                    body=json.dumps({"email": "lina@bank.com", "password": "incorrect"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                rejected = wrong_password.getresponse()
                rejected_payload = json.loads(rejected.read().decode("utf-8"))

                correct_password = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                correct_password.request(
                    "POST",
                    "/api/auth/login",
                    body=json.dumps({"email": "lina@bank.com", "password": DEFAULT_ACCOUNT_PASSWORD}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                accepted = correct_password.getresponse()
                accepted_payload = json.loads(accepted.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(rejected.status, 400)
        self.assertEqual(rejected_payload["error"], "invalid_request")
        self.assertEqual(rejected_payload["message"], "账号或密码不正确，请确认后重试。")
        self.assertEqual(accepted.status, 200)
        self.assertEqual(accepted_payload["user"]["id"], "u_lina")

    def test_idle_absolute_and_access_expiry_are_enforced(self) -> None:
        store = InMemorySessionStore()
        grant = store.issue(
            "u_admin",
            "tenant_demo",
            ("tenant_demo",),
            access_ttl_seconds=100,
            idle_timeout_seconds=200,
            absolute_timeout_seconds=300,
            now=1_000,
        )
        store.validate_access(grant.access_jti, grant.device_session_id, "u_admin", "tenant_demo", now=1_050)
        with self.assertRaisesRegex(AuthenticationError, "access_session_expired"):
            store.validate_access(grant.access_jti, grant.device_session_id, "u_admin", "tenant_demo", now=1_101)
        rotated = store.rotate_refresh(grant.refresh_token, access_ttl_seconds=100, now=1_100)
        store.validate_access(rotated.access_jti, rotated.device_session_id, "u_admin", "tenant_demo", now=1_199)
        with self.assertRaisesRegex(AuthenticationError, "session_absolute_timeout"):
            store.rotate_refresh(rotated.refresh_token, access_ttl_seconds=100, now=1_300)

    def test_sqlite_refresh_rotation_and_revocation_survive_restart(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "platform.sqlite"
            apply_migrations(db_path)
            first_store = SQLiteSessionStore(db_path)
            grant = first_store.issue(
                "u_admin",
                "tenant_demo",
                ("tenant_demo",),
                access_ttl_seconds=100,
                idle_timeout_seconds=200,
                absolute_timeout_seconds=1_000,
                now=1_000,
            )
            rotated = first_store.rotate_refresh(grant.refresh_token, access_ttl_seconds=100, now=1_050)
            with self.assertRaisesRegex(AuthenticationError, "refresh_session_revoked_or_unknown"):
                first_store.rotate_refresh(grant.refresh_token, access_ttl_seconds=100, now=1_051)
            first_store.revoke(refresh_token=rotated.refresh_token, now=1_060)
            first_store.close()

            rebuilt = SQLiteSessionStore(db_path)
            with self.assertRaisesRegex(AuthenticationError, "session_revoked_or_unknown"):
                rebuilt.validate_access(
                    rotated.access_jti,
                    rotated.device_session_id,
                    "u_admin",
                    "tenant_demo",
                    now=1_061,
                )
            rebuilt.close()

    def test_http_refresh_rotates_both_tokens_and_logout_revokes_session(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                unauthenticated = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                unauthenticated.request(
                    "GET",
                    "/api/auth/me",
                    headers={"X-User-Id": "u_admin", "X-Tenant-Id": "tenant_demo"},
                )
                unauthenticated_response = unauthenticated.getresponse()
                unauthenticated_response.read()
                self.assertEqual(unauthenticated_response.status, 401)

                login = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                login.request(
                    "POST",
                    "/api/auth/login",
                    body=json.dumps({"email": "lina@bank.com", "password": DEFAULT_ACCOUNT_PASSWORD}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                login_response = login.getresponse()
                login_payload = json.loads(login_response.read().decode("utf-8"))
                initial = _cookie_jar(login_response)
                self.assertEqual(set(initial), {"sda_session", "sda_refresh"})
                self.assertTrue(login_payload["tenant_directory"])
                self.assertIn(
                    login_payload["tenant_id"],
                    {item["id"] for item in login_payload["tenant_directory"]},
                )

                refresh = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                refresh.request("POST", "/api/auth/refresh", headers={"Cookie": _cookie_header(initial)})
                refresh_response = refresh.getresponse()
                refresh_payload = json.loads(refresh_response.read().decode("utf-8"))
                rotated = _cookie_jar(refresh_response)
                self.assertEqual(refresh_response.status, 200)
                self.assertEqual(refresh_payload["session"]["tenant_directory"], login_payload["tenant_directory"])
                self.assertNotEqual(rotated["sda_session"], initial["sda_session"])
                self.assertNotEqual(rotated["sda_refresh"], initial["sda_refresh"])

                old_access = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                old_access.request("GET", "/api/auth/me", headers={"Cookie": _cookie_header(initial)})
                old_access_response = old_access.getresponse()
                old_access_response.read()
                self.assertEqual(old_access_response.status, 401)

                me = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                me.request("GET", "/api/auth/me", headers={"Cookie": _cookie_header(rotated)})
                me_response = me.getresponse()
                me_payload = json.loads(me_response.read().decode("utf-8"))
                self.assertEqual(me_response.status, 200)
                self.assertEqual(me_payload["user"]["id"], "u_lina")
                self.assertEqual(me_payload["tenant_directory"], login_payload["tenant_directory"])

                logout = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                logout.request("POST", "/api/auth/logout", headers={"Cookie": _cookie_header(rotated)})
                logout_response = logout.getresponse()
                logout_response.read()
                self.assertEqual(logout_response.status, 200)

                after_logout = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                after_logout.request("GET", "/api/auth/me", headers={"Cookie": _cookie_header(rotated)})
                after_logout_response = after_logout.getresponse()
                after_logout_response.read()
                self.assertEqual(after_logout_response.status, 401)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
