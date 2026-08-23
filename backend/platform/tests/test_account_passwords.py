from __future__ import annotations

import http.client
import json
import threading
import unittest
from tempfile import TemporaryDirectory

from backend.authz import normalize_tenant_id
from backend.platform.access.passwords import DEFAULT_ACCOUNT_PASSWORD, hash_password, verify_password
from backend.platform.api.server import create_server
from backend.platform.bootstrap import build_local_platform
from backend.platform.tenancy import ExecutionContext


class AccountPasswordTest(unittest.TestCase):
    def test_password_hashes_are_salted_and_not_plaintext(self) -> None:
        first = hash_password(DEFAULT_ACCOUNT_PASSWORD)
        second = hash_password(DEFAULT_ACCOUNT_PASSWORD)
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password(first, DEFAULT_ACCOUNT_PASSWORD))
        self.assertFalse(verify_password(first, "wrong-password"))
        self.assertNotIn(DEFAULT_ACCOUNT_PASSWORD, first)

    def test_seeded_accounts_use_the_default_password_and_can_change_it(self) -> None:
        services = build_local_platform()
        self.addCleanup(services.close)
        self.assertTrue(services.access_service.verify_password("u_lina", DEFAULT_ACCOUNT_PASSWORD))
        services.access_service.change_password("u_lina", DEFAULT_ACCOUNT_PASSWORD, "lina-own-pass")
        self.assertFalse(services.access_service.verify_password("u_lina", DEFAULT_ACCOUNT_PASSWORD))
        self.assertTrue(services.access_service.verify_password("u_lina", "lina-own-pass"))
        self.assertTrue(services.access_service.verify_password("u_super_admin", DEFAULT_ACCOUNT_PASSWORD))
        created = services.access_service.upsert_user(
            ExecutionContext("u_super_admin", normalize_tenant_id("华兴银行")),
            {
                "name": "新加用户",
                "email": "new-password-user@example.com",
                "status": "active",
                "tenantRoles": [{"tenant": "华兴银行", "role": "操作员"}],
            },
        )
        self.assertTrue(services.access_service.verify_password(created["id"], DEFAULT_ACCOUNT_PASSWORD))
        self.assertFalse(services.access_service.verify_password(created["id"], "lina-own-pass"))

    def test_http_login_and_password_change_are_per_account(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                lina = self._json(port, "POST", "/api/auth/login", {"email": "lina@bank.com", "password": DEFAULT_ACCOUNT_PASSWORD}, want_cookie=True)
                self.assertEqual(lina[0], 200)
                changed = self._json(
                    port,
                    "POST",
                    "/api/auth/password",
                    {"current_password": DEFAULT_ACCOUNT_PASSWORD, "new_password": "lina-secret-9"},
                    cookie=lina[2],
                )
                self.assertEqual(changed[0], 200)
                rejected = self._json(port, "POST", "/api/auth/login", {"email": "lina@bank.com", "password": DEFAULT_ACCOUNT_PASSWORD})
                self.assertEqual(rejected[0], 400)
                accepted = self._json(port, "POST", "/api/auth/login", {"email": "lina@bank.com", "password": "lina-secret-9"})
                self.assertEqual(accepted[0], 200)
                admin = self._json(port, "POST", "/api/auth/login", {"email": "xujingbo-jk@qifu.com", "password": DEFAULT_ACCOUNT_PASSWORD})
                self.assertEqual(admin[0], 200)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_login_survey_creates_one_tenant_scoped_message_per_submission(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                base = {
                    "email": "lina@bank.com",
                    "password": DEFAULT_ACCOUNT_PASSWORD,
                    "institution": "华兴银行",
                }
                first = self._json(port, "POST", "/api/auth/login", {
                    **base,
                    "survey": {
                        "message_id": "mb_11111111111111111111111111111111",
                        "needed_metrics": "客户转化率和逾期迁徙率",
                        "report_usage": "晨会复盘与月度经营汇报",
                    },
                })
                second = self._json(port, "POST", "/api/auth/login", {
                    **base,
                    "survey": {
                        "message_id": "mb_22222222222222222222222222222222",
                        "needed_metrics": "分支机构目标完成率",
                        "report_usage": "每日经营跟踪",
                    },
                })
                retry = self._json(port, "POST", "/api/auth/login", {
                    **base,
                    "survey": {
                        "message_id": "mb_22222222222222222222222222222222",
                        "needed_metrics": "分支机构目标完成率",
                        "report_usage": "每日经营跟踪",
                    },
                })
                partial = self._json(port, "POST", "/api/auth/login", {
                    **base,
                    "survey": {
                        "message_id": "mb_33333333333333333333333333333333",
                        "needed_metrics": "仅填写一个问题",
                        "report_usage": "",
                        "trigger": "login",
                    },
                })
                rejected = self._json(port, "POST", "/api/auth/login", {
                    **base,
                    "password": "wrong-password",
                    "survey": {
                        "message_id": "mb_44444444444444444444444444444444",
                        "needed_metrics": "登录失败时也保存",
                        "report_usage": "用于经营复盘",
                        "trigger": "login",
                    },
                })
                cancelled = self._json(port, "POST", "/api/auth/login-survey", {
                    "account": "",
                    "institution": "华兴银行",
                    "survey": {
                        "message_id": "mb_55555555555555555555555555555555",
                        "needed_metrics": "取消页面前填写的指标",
                        "report_usage": "",
                        "trigger": "cancel",
                    },
                })
                pagehide_retry = self._json(port, "POST", "/api/auth/login-survey", {
                    "account": "",
                    "institution": "华兴银行",
                    "survey": {
                        "message_id": "mb_55555555555555555555555555555555",
                        "needed_metrics": "取消页面前填写的指标",
                        "report_usage": "",
                        "trigger": "pagehide",
                    },
                })
                empty = self._json(port, "POST", "/api/auth/login-survey", {
                    "institution": "华兴银行",
                    "survey": {
                        "message_id": "mb_66666666666666666666666666666666",
                        "needed_metrics": "",
                        "report_usage": "",
                        "trigger": "pagehide",
                    },
                })
                tenant_id = first[1]["tenant_id"]
                board = server.services.message_board_service.list_all(tenant_id=tenant_id, page_size=20)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(first[0], 200)
        self.assertEqual(second[0], 200)
        self.assertEqual(retry[0], 200)
        self.assertEqual(partial[0], 200)
        self.assertEqual(rejected[0], 400)
        self.assertEqual(cancelled[0], 201)
        self.assertEqual(pagehide_retry[0], 201)
        self.assertEqual(empty[0], 200)
        self.assertEqual(empty[1]["status"], "ignored_empty")
        self.assertEqual(board["total"], 5)
        self.assertEqual({item["message_id"] for item in board["messages"]}, {
            "mb_11111111111111111111111111111111",
            "mb_22222222222222222222222222222222",
            "mb_33333333333333333333333333333333",
            "mb_44444444444444444444444444444444",
            "mb_55555555555555555555555555555555",
        })
        self.assertTrue(all(item["page_key"] == "login-survey" for item in board["messages"]))
        self.assertEqual(sum(item["author_user_id"] == "u_lina" for item in board["messages"]), 4)
        self.assertEqual(sum(item["author_user_id"] == "u_super_admin" for item in board["messages"]), 1)
        self.assertEqual(sum(item["author_name"] == "登录页访客" for item in board["messages"]), 1)
        self.assertIn("你需要什么指标？", board["messages"][0]["content"])
        self.assertIn("（未填写）", "\n".join(item["content"] for item in board["messages"]))
        self.assertIn("登录前自动保存", "\n".join(item["content"] for item in board["messages"]))
        self.assertNotIn(DEFAULT_ACCOUNT_PASSWORD, "\n".join(item["content"] for item in board["messages"]))

    def _json(self, port: int, method: str, path: str, payload: dict | None = None, *, cookie: str = "", want_cookie: bool = False):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=8)
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        body = json.dumps(payload or {}).encode("utf-8") if payload is not None and method != "GET" else None
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8")
        parsed = json.loads(raw) if raw else {}
        cookie_header = response.getheader("Set-Cookie") or ""
        return (response.status, parsed, cookie_header) if want_cookie else (response.status, parsed)


if __name__ == "__main__":
    unittest.main()
