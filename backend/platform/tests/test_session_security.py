from __future__ import annotations

import http.client
import json
import threading
from http.cookies import SimpleCookie
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import quote

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


def _json_request(
    port: int,
    method: str,
    path: str,
    *,
    jar: dict[str, str] | None = None,
    tenant_id: str = "",
    payload: dict | None = None,
) -> tuple[int, dict, dict[str, str]]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if jar:
        headers["Cookie"] = _cookie_header(jar)
    if tenant_id:
        headers["X-Tenant-Id"] = quote(tenant_id)
    if body is not None:
        headers["Content-Type"] = "application/json"
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    raw = response.read().decode("utf-8")
    response_cookies = _cookie_jar(response)
    connection.close()
    return response.status, json.loads(raw) if raw else {}, response_cookies


class SessionSecurityTest(unittest.TestCase):
    def test_stateful_session_does_not_treat_wildcard_as_catalog_authority(self) -> None:
        store = InMemorySessionStore()
        grant = store.issue(
            "u_super_admin",
            "tenant_demo",
            ("*", "tenant_demo"),
            access_ttl_seconds=100,
            idle_timeout_seconds=200,
            absolute_timeout_seconds=300,
            now=1_000,
        )

        with self.assertRaisesRegex(AuthenticationError, "session_tenant_not_allowed"):
            store.validate_access(
                grant.access_jti,
                grant.device_session_id,
                "u_super_admin",
                "tenant:not-in-active-catalog",
                now=1_050,
            )

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

    def test_sqlite_refresh_scope_reconciliation_survives_restart(self) -> None:
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
            resolved = first_store.resolve_refresh(grant.refresh_token, now=1_010)
            self.assertEqual(resolved.user_id, "u_admin")
            rotated = first_store.rotate_refresh(
                grant.refresh_token,
                access_ttl_seconds=100,
                primary_tenant_id="tenant:created",
                tenant_ids=("tenant_demo", "tenant:created"),
                now=1_020,
            )
            first_store.close()

            rebuilt = SQLiteSessionStore(db_path)
            rebuilt.validate_access(
                rotated.access_jti,
                rotated.device_session_id,
                "u_admin",
                "tenant:created",
                now=1_030,
            )
            with self.assertRaisesRegex(AuthenticationError, "session_identity_mismatch"):
                rebuilt.validate_access(
                    grant.access_jti,
                    grant.device_session_id,
                    "u_admin",
                    "tenant:created",
                    now=1_030,
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

    def test_refresh_reconciles_a_super_admin_session_with_a_new_tenant(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                login_status, login, initial = _json_request(
                    port,
                    "POST",
                    "/api/auth/login",
                    payload={"email": "xujingbo-jk@qifu.com", "password": DEFAULT_ACCOUNT_PASSWORD},
                )
                primary_tenant = login["tenant_id"]
                create_status, created, _ = _json_request(
                    port,
                    "POST",
                    "/api/tenants",
                    jar=initial,
                    tenant_id=primary_tenant,
                    payload={"name": "刷新会话银行"},
                )
                created_tenant = created["tenant"]["id"]

                before_status, _, _ = _json_request(
                    port,
                    "GET",
                    "/api/system-config",
                    jar=initial,
                    tenant_id=created_tenant,
                )
                refresh_status, refresh_payload, rotated = _json_request(
                    port,
                    "POST",
                    "/api/auth/refresh",
                    jar=initial,
                )
                after_status, config, _ = _json_request(
                    port,
                    "GET",
                    "/api/system-config",
                    jar=rotated,
                    tenant_id=created_tenant,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(login_status, 200)
        self.assertEqual(create_status, 200)
        self.assertEqual(before_status, 401)
        self.assertEqual(refresh_status, 200)
        self.assertIn(created_tenant, {item["id"] for item in refresh_payload["session"]["tenant_directory"]})
        self.assertEqual(after_status, 200)
        self.assertTrue(config["can_read_system_params"])
        self.assertIn(created_tenant, config["parameter_tenant_ids"])

    def test_tenant_switch_rotates_session_and_rejects_unauthorized_user(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                _, super_login, super_jar = _json_request(
                    port,
                    "POST",
                    "/api/auth/login",
                    payload={"email": "xujingbo-jk@qifu.com", "password": DEFAULT_ACCOUNT_PASSWORD},
                )
                create_status, created, _ = _json_request(
                    port,
                    "POST",
                    "/api/tenants",
                    jar=super_jar,
                    tenant_id=super_login["tenant_id"],
                    payload={"name": "权威切换银行"},
                )
                created_tenant = created["tenant"]["id"]
                switch_status, switched, switched_jar = _json_request(
                    port,
                    "POST",
                    "/api/auth/switch-tenant",
                    jar=super_jar,
                    payload={"tenant_id": created_tenant},
                )
                old_status, _, _ = _json_request(port, "GET", "/api/auth/me", jar=super_jar)
                current_status, current, _ = _json_request(port, "GET", "/api/auth/me", jar=switched_jar)
                config_status, config, _ = _json_request(
                    port,
                    "GET",
                    "/api/system-config",
                    jar=switched_jar,
                    tenant_id=created_tenant,
                )
                metrics_status, metrics, _ = _json_request(
                    port,
                    "GET",
                    "/api/metric-dictionary",
                    jar=switched_jar,
                    tenant_id=created_tenant,
                )
                invalid_status, invalid, _ = _json_request(
                    port,
                    "POST",
                    "/api/auth/switch-tenant",
                    jar=switched_jar,
                    payload={"tenant_id": "tenant:not-in-catalog"},
                )
                preserved_status, preserved, _ = _json_request(port, "GET", "/api/auth/me", jar=switched_jar)

                _, _, operator_jar = _json_request(
                    port,
                    "POST",
                    "/api/auth/login",
                    payload={"email": "lina@bank.com", "password": DEFAULT_ACCOUNT_PASSWORD},
                )
                denied_status, denied, _ = _json_request(
                    port,
                    "POST",
                    "/api/auth/switch-tenant",
                    jar=operator_jar,
                    payload={"tenant_id": created_tenant},
                )
                operator_status, operator_session, _ = _json_request(port, "GET", "/api/auth/me", jar=operator_jar)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(create_status, 200)
        self.assertEqual(switch_status, 200)
        self.assertEqual(switched["tenant_id"], created_tenant)
        self.assertEqual(switched["institution"], "权威切换银行")
        self.assertEqual(set(switched_jar), {"sda_session", "sda_refresh"})
        self.assertEqual(old_status, 401)
        self.assertEqual(current_status, 200)
        self.assertEqual(current["tenant_id"], created_tenant)
        self.assertEqual(config_status, 200)
        self.assertTrue(config["can_read_system_params"])
        self.assertEqual(metrics_status, 200)
        self.assertEqual(metrics["metrics"], [])
        self.assertEqual(invalid_status, 403)
        self.assertEqual(invalid["error"], "tenant_context_conflict")
        self.assertEqual(preserved_status, 200)
        self.assertEqual(preserved["tenant_id"], created_tenant)
        self.assertEqual(denied_status, 403)
        self.assertEqual(denied["error"], "tenant_context_conflict")
        self.assertEqual(operator_status, 200)
        self.assertNotEqual(operator_session["tenant_id"], created_tenant)


if __name__ == "__main__":
    unittest.main()
