from __future__ import annotations

import http.client
import json
import threading
import unittest
from tempfile import TemporaryDirectory

from backend.platform.api.server import create_server


class VisibleAccountNamesTest(unittest.TestCase):
    def test_todo_and_audit_return_profile_name_while_preserving_subject_id(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                create_status, created = self._request(port, "POST", "/api/application/action", {
                    "module_key": "agent_workspace",
                    "action": "create_todo",
                    "payload": {"todo": {"title": "姓名展示回归"}},
                })
                audit_status, audit = self._request(port, "GET", "/api/audit-logs?limit=20&offset=0")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        todo = created["result"]["todo"]
        self.assertEqual(create_status, 200)
        self.assertEqual(todo["assignee"], "胥京波")
        self.assertEqual(todo["assigneeUserId"], "u_super_admin")
        self.assertEqual(todo["ownerUserId"], "u_super_admin")
        self.assertEqual(audit_status, 200)
        action_log = next(item for item in audit["logs"] if item["action"] == "application.create_todo")
        self.assertEqual(action_log["actor_user_id"], "u_super_admin")
        self.assertEqual(action_log["actor_name"], "胥京波")

    @staticmethod
    def _request(port: int, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = {"X-User-Id": "u_super_admin", "X-Tenant-Id": "tenant_demo"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8")
        connection.close()
        return response.status, json.loads(raw) if raw else {}


if __name__ == "__main__":
    unittest.main()
