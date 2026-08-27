from __future__ import annotations

import http.client
import json
import threading
import unittest
from tempfile import TemporaryDirectory

from backend.authz import normalize_tenant_id
from backend.platform.access.passwords import DEFAULT_ACCOUNT_PASSWORD
from backend.platform.api.server import create_server
from backend.platform.bootstrap import build_local_platform
from backend.platform.tenancy import ExecutionContext

REGISTERED_PASSWORD = "op-own-password-123"


class RegistrationApprovalTest(unittest.TestCase):
    def test_registration_uses_active_tenant_catalog_instead_of_role_names(self) -> None:
        services = build_local_platform()
        try:
            catalog = [{"id": "tenant:catalog-only", "name": "目录专属银行", "status": "active"}]
            services.access_service._tenant_catalog = lambda: catalog
            with self.assertRaisesRegex(ValueError, "机构默认操作员角色不存在"):
                services.access_service.submit_registration_request(
                    {
                        "name": "目录用户",
                        "email": "catalog-only@example.com",
                        "password": "CatalogOnly!123",
                        "institution": "目录专属银行",
                    }
                )
        finally:
            services.close()

    def test_super_admin_session_preserves_catalog_tenant_id(self) -> None:
        services = build_local_platform()
        try:
            services.access_service._tenant_catalog = lambda: [
                {"id": "tenant:石嘴山银行", "name": "石嘴山银行", "status": "active"}
            ]
            session = services.access_service.login_by_email(
                "Xujingbo-jk@qifu.com",
                tenant_hint="tenant:石嘴山银行",
            )
        finally:
            services.close()
        self.assertEqual(session["tenant_id"], "tenant:石嘴山银行")
        self.assertEqual(session["institution"], "石嘴山银行")

    def test_super_admin_cannot_enter_inactive_or_unknown_catalog_tenant(self) -> None:
        services = build_local_platform()
        try:
            services.access_service._tenant_catalog = lambda: [
                {"id": "tenant:active", "name": "有效银行", "status": "active"}
            ]
            with self.assertRaisesRegex(PermissionError, "session_tenant_not_authorized"):
                services.access_service.login_by_email(
                    "Xujingbo-jk@qifu.com",
                    tenant_hint="tenant:missing",
                )
        finally:
            services.close()

    def test_registration_stays_pending_until_super_admin_approves(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                register = self._json(
                    port,
                    "POST",
                    "/api/auth/register",
                    {
                        "name": "待审操作员",
                        "email": "pending-op@example.com",
                        "password": REGISTERED_PASSWORD,
                        "institution": "华兴银行",
                    },
                )
                self.assertEqual(register[0], 202)
                self.assertEqual(register[1]["status"], "pending_approval")

                denied = self._json(
                    port,
                    "POST",
                    "/api/auth/login",
                    {
                        "email": "pending-op@example.com",
                        "password": REGISTERED_PASSWORD,
                    },
                )
                self.assertEqual(denied[0], 400)

                super_status, super_payload, super_cookie = self._json(
                    port,
                    "POST",
                    "/api/auth/login",
                    {"email": "xujingbo-jk@qifu.com", "password": DEFAULT_ACCOUNT_PASSWORD},
                    want_cookie=True,
                )
                self.assertEqual(super_status, 200)
                self.assertTrue(super_payload["is_super_admin"])

                todos = self._json(
                    port,
                    "GET",
                    "/api/application/module?module_key=agent_workspace",
                    cookie=super_cookie,
                )
                self.assertEqual(todos[0], 200)
                titles = [item.get("title") for item in todos[1]["state"]["todos"]]
                self.assertTrue(any("待审操作员" in str(title) and "华兴银行" in str(title) for title in titles))

                approved = self._json(
                    port,
                    "POST",
                    "/api/application/action",
                    {
                        "module_key": "agent_workspace",
                        "action": "approve_registration",
                        "payload": {"requestId": register[1]["request_id"]},
                    },
                    cookie=super_cookie,
                )
                self.assertEqual(approved[0], 200)
                self.assertEqual(approved[1]["result"]["status"], "approved")
                self.assertEqual(
                    approved[1]["result"]["user"]["user"]["tenantRoles"],
                    [{"tenant": "华兴银行", "tenantId": normalize_tenant_id("华兴银行"), "role": "操作员"}],
                )

                logged_in = self._json(
                    port,
                    "POST",
                    "/api/auth/login",
                    {
                        "email": "pending-op@example.com",
                        "password": REGISTERED_PASSWORD,
                        "institution": "华兴银行",
                    },
                )
                self.assertEqual(logged_in[0], 200)
                self.assertEqual(logged_in[1]["user"]["id"], register[1]["request_id"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_super_admin_can_reject_registration_and_phone_contact_is_accepted(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                register = self._json(
                    port,
                    "POST",
                    "/api/auth/register",
                    {
                        "phone": "13800138000",
                        "password": REGISTERED_PASSWORD,
                        "institution": "郑州银行",
                    },
                )
                self.assertEqual(register[0], 202)
                _, _, super_cookie = self._json(
                    port,
                    "POST",
                    "/api/auth/login",
                    {"email": "xujingbo-jk@qifu.com", "password": DEFAULT_ACCOUNT_PASSWORD},
                    want_cookie=True,
                )
                rejected = self._json(
                    port,
                    "POST",
                    "/api/application/action",
                    {
                        "module_key": "agent_workspace",
                        "action": "reject_registration",
                        "payload": {"requestId": register[1]["request_id"]},
                    },
                    cookie=super_cookie,
                )
                self.assertEqual(rejected[0], 200)
                self.assertEqual(rejected[1]["result"]["status"], "rejected")
                login = self._json(
                    port,
                    "POST",
                    "/api/auth/login",
                    {"email": "13800138000", "password": REGISTERED_PASSWORD},
                )
                self.assertEqual(login[0], 400)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_operator_cannot_review_registration(self) -> None:
        services = None
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            services = server.services
            pending = services.access_service.submit_registration_request(
                {"name": "越权", "email": "blocked@example.com", "institution": "华兴银行"}
            )
            with self.assertRaises(PermissionError):
                services.access_service.review_registration(
                    ExecutionContext("u_lina", normalize_tenant_id("华兴银行")),
                    pending["request_id"],
                    approved=True,
                )

    @staticmethod
    def _json(port: int, method: str, path: str, body=None, cookie: str = "", want_cookie: bool = False):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=8)
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
        data = json.loads(raw) if raw else {}
        if want_cookie:
            return response.status, data, response.getheader("Set-Cookie") or ""
        return response.status, data
