import http.client
import json
import threading
import unittest
from tempfile import TemporaryDirectory
from urllib.parse import quote

from backend.platform.api.routes.analysis import run_analysis
from backend.platform.api.server import create_server


class ContextRailVisibilityTest(unittest.TestCase):
    def test_comments_are_tenant_shared_and_analysis_is_tenant_user_private(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                report_id = "multi_institution_tenant_demo"
                created_status, created = self._request(
                    port,
                    "POST",
                    "/api/reports/comment",
                    "u_admin",
                    "tenant_demo",
                    {
                        "report_id": report_id,
                        "expected_revision": 0,
                        "client_request_id": "context-comment-create",
                        "comment": {
                            "targetId": "dashboard:consumer-kpis",
                            "targetLabel": "消费贷核心指标",
                            "selectedText": "1.31",
                            "targetKind": "paragraph",
                            "text": "请复核这一指标。",
                        },
                    },
                )
                comment_id = str(created.get("comment", {}).get("id") or "")

                peer_status, peer_view = self._request(
                    port,
                    "GET",
                    f"/api/reports/comments?report_id={quote(report_id)}",
                    "u_reviewer",
                    "tenant_demo",
                )
                reply_status, replied = self._request(
                    port,
                    "PUT",
                    "/api/reports/comment",
                    "u_reviewer",
                    "tenant_demo",
                    {
                        "report_id": report_id,
                        "comment_id": comment_id,
                        "action": "reply",
                        "payload": {"text": "已复核，口径一致。"},
                        "expected_revision": 1,
                        "client_request_id": "context-comment-reply",
                    },
                )
                other_tenant_status, other_tenant_view = self._request(
                    port,
                    "GET",
                    f"/api/reports/comments?report_id={quote(report_id)}",
                    "u_super_admin",
                    "tenant_other",
                )

                analysis = run_analysis(
                    server.services,
                    user_id="u_super_admin",
                    tenant_id="tenant_demo",
                    question="本月各分行放款金额是多少",
                )
                task_path = f"/api/analysis/task?task_id={quote(analysis['task_id'])}"
                owner_status, owner_view = self._request(port, "GET", task_path, "u_super_admin", "tenant_demo")
                peer_analysis_status, _ = self._request(port, "GET", task_path, "u_reviewer", "tenant_demo")
                other_tenant_analysis_status, _ = self._request(port, "GET", task_path, "u_super_admin", "tenant_other")
                delete_status, deleted = self._request(
                    port,
                    "DELETE",
                    "/api/reports/comment",
                    "u_admin",
                    "tenant_demo",
                    {
                        "report_id": report_id,
                        "comment_id": comment_id,
                        "expected_revision": replied["revision"],
                    },
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(created_status, 200)
        self.assertTrue(comment_id)
        self.assertEqual(peer_status, 200)
        self.assertEqual(peer_view["comments"][0]["text"], "请复核这一指标。")
        self.assertEqual(reply_status, 200)
        self.assertEqual(replied["comments"][0]["replies"][0]["text"], "已复核，口径一致。")
        self.assertEqual(created["comment"]["author"], "平台管理员")
        self.assertEqual(replied["comments"][0]["replies"][0]["author"], "平台复核员")
        self.assertEqual(other_tenant_status, 200)
        self.assertEqual(other_tenant_view["comments"], [])
        self.assertEqual(owner_status, 200)
        self.assertEqual(owner_view["task"]["user_id"], "u_super_admin")
        self.assertEqual(peer_analysis_status, 403)
        self.assertEqual(other_tenant_analysis_status, 403)
        self.assertEqual(delete_status, 200)
        self.assertEqual(deleted["comments"], [])

    @staticmethod
    def _request(
        port: int,
        method: str,
        path: str,
        user_id: str,
        tenant_id: str,
        payload: dict | None = None,
    ) -> tuple[int, dict]:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = {"X-User-Id": user_id, "X-Tenant-Id": tenant_id}
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8")
        connection.close()
        return response.status, json.loads(raw) if raw else {}


if __name__ == "__main__":
    unittest.main()
