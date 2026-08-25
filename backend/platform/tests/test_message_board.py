from __future__ import annotations

import base64
import html
import http.client
import json
import threading
import unittest
from io import BytesIO
from tempfile import TemporaryDirectory
from urllib.parse import quote
from zipfile import ZipFile

from backend.platform.api.server import create_server


class MessageBoardTest(unittest.TestCase):
    def test_historical_internal_author_id_is_resolved_to_profile_name(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            try:
                server.services.message_board_store.create({
                    "message_id": "mb_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "tenant_id": "tenant_demo",
                    "author_user_id": "u_super_admin",
                    "author_name": "u_super_admin",
                    "page_key": "weekly-report",
                    "page_title": "经营周报",
                    "page_url": "/weekly-report",
                    "content": "历史留言",
                    "quote_context": {},
                    "attachment_ids": [],
                })
                result = server.services.message_board_service.list_all()
            finally:
                server.server_close()

        self.assertEqual(result["messages"][0]["author_user_id"], "u_super_admin")
        self.assertEqual(result["messages"][0]["author_name"], "胥京波")

    def test_admin_list_filters_by_status_and_sorts_created_at(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                for index, status in enumerate(("new", "adopted", "completed"), start=1):
                    message_id = f"mb_{index:032x}"
                    create_status, _ = self._request(port, "POST", "/api/message-board", "u_reviewer", "tenant_demo", {
                        "message_id": message_id,
                        "page_key": "self-analysis/query",
                        "page_title": "智能分析",
                        "page_url": "/self-analysis/query",
                        "content": f"状态{status}留言",
                        "quote_context": {},
                        "attachment_ids": [],
                    })
                    self.assertEqual(create_status, 200)
                    if status != "new":
                        listed_status, listed = self._request(port, "GET", "/api/message-board/admin", "u_super_admin", "tenant_demo")
                        self.assertEqual(listed_status, 200)
                        message = next(item for item in listed["messages"] if item["message_id"] == message_id)
                        update_status, _ = self._request(port, "PUT", "/api/message-board/admin/status", "u_super_admin", "tenant_demo", {
                            "message_id": message["message_id"],
                            "status": status,
                            "expected_lock_version": message["lock_version"],
                        })
                        self.assertEqual(update_status, 200)
                adopted_status, adopted = self._request(port, "GET", "/api/message-board/admin?status=adopted", "u_super_admin", "tenant_demo")
                asc_status, ascending = self._request(port, "GET", "/api/message-board/admin?sort=asc", "u_super_admin", "tenant_demo")
                desc_status, descending = self._request(port, "GET", "/api/message-board/admin?sort=desc", "u_super_admin", "tenant_demo")
                invalid_status, invalid = self._request(port, "GET", "/api/message-board/admin?status=archived", "u_super_admin", "tenant_demo")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(adopted_status, 200)
        self.assertEqual([item["status"] for item in adopted["messages"]], ["adopted"])
        self.assertEqual(asc_status, 200)
        self.assertEqual(desc_status, 200)
        self.assertEqual(
            [item["message_id"] for item in ascending["messages"]],
            list(reversed([item["message_id"] for item in descending["messages"]])),
        )
        self.assertEqual(invalid_status, 400)
        self.assertEqual(invalid["error"], "invalid_request")

    def test_owner_delete_removes_message_from_owner_and_admin_reads(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                message_id = "mb_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                created_status, _ = self._request(port, "POST", "/api/message-board", "u_reviewer", "tenant_demo", {
                    "message_id": message_id, "page_key": "self-analysis", "page_title": "智能分析",
                    "page_url": "/self-analysis/query", "content": "一次性删除测试留言", "quote_context": {}, "attachment_ids": [],
                })
                peer_delete_status, _ = self._request(port, "DELETE", "/api/message-board", "u_super_admin", "tenant_demo", {
                    "message_id": message_id, "expected_lock_version": 0,
                })
                update_status, updated = self._request(port, "PUT", "/api/message-board", "u_reviewer", "tenant_demo", {
                    "message_id": message_id, "content": "更新后的删除测试留言", "quote_context": {}, "attachment_ids": [], "expected_lock_version": 0,
                })
                stale_delete_status, _ = self._request(port, "DELETE", "/api/message-board", "u_reviewer", "tenant_demo", {
                    "message_id": message_id, "expected_lock_version": 0,
                })
                delete_status, deleted = self._request(port, "DELETE", "/api/message-board", "u_reviewer", "tenant_demo", {
                    "message_id": message_id, "expected_lock_version": updated["message"]["lock_version"],
                })
                owner_status, owner = self._request(port, "GET", "/api/message-board?page_key=self-analysis", "u_reviewer", "tenant_demo")
                admin_status, admin = self._request(port, "GET", "/api/message-board/admin", "u_super_admin", "tenant_demo")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(created_status, 200)
        self.assertEqual(peer_delete_status, 403)
        self.assertEqual(update_status, 200)
        self.assertEqual(stale_delete_status, 409)
        self.assertEqual(delete_status, 200)
        self.assertEqual(deleted["deleted_message_id"], message_id)
        self.assertEqual(owner_status, 200)
        self.assertEqual(owner["messages"], [])
        self.assertEqual(admin_status, 200)
        self.assertEqual(admin["total"], 0)

    def test_owner_scope_tenant_scope_and_super_admin_management(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                message_id = "mb_0123456789abcdef0123456789abcdef"
                created_status, created = self._request(port, "POST", "/api/message-board", "u_reviewer", "tenant_demo", {
                    "message_id": message_id,
                    "page_key": "weekly-report",
                    "page_title": "经营周报",
                    "page_url": "/weekly-report",
                    "content": "希望图表可以导出高清图片。",
                    "quote_context": {"target_id": "chart-1", "target_type": "图表", "label": "放款趋势", "selected_text": "本周环比提升 8%"},
                    "attachment_ids": [],
                })
                owner_status, owner = self._request(port, "GET", f"/api/message-board?page_key={quote('weekly-report')}", "u_reviewer", "tenant_demo")
                peer_status, peer = self._request(port, "GET", f"/api/message-board?page_key={quote('weekly-report')}", "u_super_admin", "tenant_demo")
                other_tenant_status, other_tenant = self._request(port, "GET", f"/api/message-board?page_key={quote('weekly-report')}", "u_reviewer", "tenant_other")
                non_admin_status, _ = self._request(port, "GET", "/api/message-board/admin", "u_reviewer", "tenant_demo")
                admin_status, admin = self._request(port, "GET", "/api/message-board/admin", "u_super_admin", "tenant_demo")
                peer_update_status, _ = self._request(port, "PUT", "/api/message-board", "u_super_admin", "tenant_demo", {
                    "message_id": message_id, "content": "越权修改", "quote_context": {}, "attachment_ids": [], "expected_lock_version": 0,
                })
                update_status, updated = self._request(port, "PUT", "/api/message-board", "u_reviewer", "tenant_demo", {
                    "message_id": message_id, "content": "希望图表可导出高清 PNG。", "quote_context": created["message"]["quote_context"], "attachment_ids": [], "expected_lock_version": 0,
                })
                stale_status, stale = self._request(port, "PUT", "/api/message-board", "u_reviewer", "tenant_demo", {
                    "message_id": message_id, "content": "旧页面覆盖", "quote_context": {}, "attachment_ids": [], "expected_lock_version": 0,
                })
                non_admin_status_update, _ = self._request(port, "PUT", "/api/message-board/admin/status", "u_reviewer", "tenant_demo", {
                    "message_id": message_id, "status": "adopted", "expected_lock_version": 1,
                })
                adopted_status, adopted = self._request(port, "PUT", "/api/message-board/admin/status", "u_super_admin", "tenant_demo", {
                    "message_id": message_id, "status": "adopted", "expected_lock_version": 1,
                })
                stale_status_update, _ = self._request(port, "PUT", "/api/message-board/admin/status", "u_super_admin", "tenant_demo", {
                    "message_id": message_id, "status": "completed", "expected_lock_version": 1,
                })
                peer_archive_status, _ = self._request(port, "PUT", "/api/message-board/archive", "u_super_admin", "tenant_demo", {
                    "message_id": message_id, "expected_lock_version": 2,
                })
                archive_status, archived = self._request(port, "PUT", "/api/message-board/archive", "u_reviewer", "tenant_demo", {
                    "message_id": message_id, "expected_lock_version": 2,
                })
                completed_edit_status, _ = self._request(port, "PUT", "/api/message-board", "u_reviewer", "tenant_demo", {
                    "message_id": message_id, "content": "归档后继续编辑", "quote_context": {}, "attachment_ids": [], "expected_lock_version": 3,
                })
                final_owner_status, final_owner = self._request(port, "GET", f"/api/message-board?page_key={quote('weekly-report')}", "u_reviewer", "tenant_demo")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(created_status, 200)
        self.assertEqual(created["message"]["author_name"], "平台复核员")
        self.assertEqual(created["message"]["status"], "new")
        self.assertEqual(owner_status, 200)
        self.assertEqual(owner["messages"][0]["message_id"], message_id)
        self.assertEqual(peer_status, 200)
        self.assertEqual(peer["messages"], [])
        self.assertEqual(other_tenant_status, 200)
        self.assertEqual(other_tenant["messages"], [])
        self.assertEqual(non_admin_status, 403)
        self.assertEqual(admin_status, 200)
        self.assertEqual(admin["total"], 1)
        self.assertEqual(admin["messages"][0]["author_user_id"], "u_reviewer")
        self.assertEqual(admin["messages"][0]["author_name"], "平台复核员")
        self.assertEqual(peer_update_status, 403)
        self.assertEqual(update_status, 200)
        self.assertEqual(updated["message"]["lock_version"], 1)
        self.assertEqual(stale_status, 409)
        self.assertEqual(stale["error"], "message_board_revision_conflict")
        self.assertEqual(non_admin_status_update, 403)
        self.assertEqual(adopted_status, 200)
        self.assertEqual(adopted["message"]["status"], "adopted")
        self.assertEqual(adopted["message"]["lock_version"], 2)
        self.assertEqual(stale_status_update, 409)
        self.assertEqual(peer_archive_status, 403)
        self.assertEqual(archive_status, 200)
        self.assertEqual(archived["message"]["status"], "completed")
        self.assertIsNotNone(archived["message"]["archived_at"])
        self.assertEqual(completed_edit_status, 403)
        self.assertEqual(final_owner_status, 200)
        self.assertEqual(final_owner["messages"][0]["status"], "completed")

    def test_navigation_management_item_is_super_admin_only(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                super_status, super_nav = self._request(port, "GET", "/api/navigation", "u_super_admin", "tenant_demo")
                reviewer_status, reviewer_nav = self._request(port, "GET", "/api/navigation", "u_reviewer", "tenant_demo")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(super_status, 200)
        self.assertIn("task-workbench.message-board", super_nav["menu_keys"])
        self.assertEqual(reviewer_status, 200)
        self.assertNotIn("task-workbench.message-board", reviewer_nav["menu_keys"])

    def test_admin_list_and_status_stay_on_selected_tenant(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                demo_id = "mb_cccccccccccccccccccccccccccccccc"
                other_id = "mb_dddddddddddddddddddddddddddddddd"
                created_demo, _ = self._request(port, "POST", "/api/message-board", "u_reviewer", "tenant_demo", {
                    "message_id": demo_id, "page_key": "weekly-report", "page_title": "经营周报",
                    "page_url": "/weekly-report", "content": "演示机构留言", "quote_context": {}, "attachment_ids": [],
                })
                created_other, _ = self._request(port, "POST", "/api/message-board", "u_super_admin", "tenant_other", {
                    "message_id": other_id, "page_key": "weekly-report", "page_title": "经营周报",
                    "page_url": "/weekly-report", "content": "其他机构留言", "quote_context": {}, "attachment_ids": [],
                })
                demo_admin_status, demo_admin = self._request(port, "GET", "/api/message-board/admin", "u_super_admin", "tenant_demo")
                other_admin_status, other_admin = self._request(port, "GET", "/api/message-board/admin", "u_super_admin", "tenant_other")
                cross_status, _ = self._request(port, "PUT", "/api/message-board/admin/status", "u_super_admin", "tenant_demo", {
                    "message_id": other_id, "status": "adopted", "expected_lock_version": 0,
                })
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(created_demo, 200)
        self.assertEqual(created_other, 200)
        self.assertEqual(demo_admin_status, 200)
        self.assertEqual(other_admin_status, 200)
        self.assertEqual([item["message_id"] for item in demo_admin["messages"]], [demo_id])
        self.assertEqual([item["message_id"] for item in other_admin["messages"]], [other_id])
        self.assertEqual(demo_admin["tenant_id"], "tenant_demo")
        self.assertEqual(other_admin["tenant_id"], "tenant_other")
        self.assertEqual(cross_status, 403)

    def test_append_content_and_adopted_export(self) -> None:
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                adopted_id = "mb_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
                ignored_id = "mb_ffffffffffffffffffffffffffffffff"
                image_status, image = self._request(port, "POST", "/api/message-board/image", "u_reviewer", "tenant_demo", {
                    "message_id": adopted_id,
                    "file_name": "screenshot.png",
                    "content_base64": base64.b64encode(png).decode("ascii"),
                })
                created_adopted, created = self._request(port, "POST", "/api/message-board", "u_reviewer", "tenant_demo", {
                    "message_id": adopted_id, "page_key": "weekly-report", "page_title": "经营周报",
                    "page_url": "/weekly-report", "content": "请导出截图", "quote_context": {"selected_text": "本周环比"},
                    "attachment_ids": [image["attachment"]["attachment_id"]],
                })
                created_new, _ = self._request(port, "POST", "/api/message-board", "u_reviewer", "tenant_demo", {
                    "message_id": ignored_id, "page_key": "weekly-report", "page_title": "经营周报",
                    "page_url": "/weekly-report", "content": "未采纳留言", "quote_context": {}, "attachment_ids": [],
                })
                non_admin_append, _ = self._request(port, "PUT", "/api/message-board/admin/append-content", "u_reviewer", "tenant_demo", {
                    "message_id": adopted_id, "append_content": "越权追加", "expected_lock_version": 0,
                })
                append_status, appended = self._request(port, "PUT", "/api/message-board/admin/append-content", "u_super_admin", "tenant_demo", {
                    "message_id": adopted_id, "append_content": "已安排下周处理", "expected_lock_version": 0,
                })
                reload_status, reloaded = self._request(port, "GET", "/api/message-board/admin", "u_super_admin", "tenant_demo")
                adopted_status, adopted = self._request(port, "PUT", "/api/message-board/admin/status", "u_super_admin", "tenant_demo", {
                    "message_id": adopted_id, "status": "adopted", "expected_lock_version": appended["message"]["lock_version"],
                })
                non_admin_export_status, _raw, _headers = self._request_bytes(port, "GET", "/api/message-board/admin/export?status=adopted&format=excel", "u_reviewer", "tenant_demo")
                export_status, export_body, export_headers = self._request_bytes(port, "GET", "/api/message-board/admin/export?status=adopted&format=feishu", "u_super_admin", "tenant_demo")
                other_export_status, other_body, other_headers = self._request_bytes(port, "GET", "/api/message-board/admin/export?status=adopted&format=excel", "u_super_admin", "tenant_other")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(image_status, 200)
        self.assertEqual(created_adopted, 200)
        self.assertEqual(created_new, 200)
        self.assertEqual(non_admin_append, 403)
        self.assertEqual(append_status, 200)
        self.assertEqual(appended["message"]["append_content"], "已安排下周处理")
        self.assertEqual(reload_status, 200)
        self.assertEqual(next(item["append_content"] for item in reloaded["messages"] if item["message_id"] == adopted_id), "已安排下周处理")
        self.assertEqual(adopted_status, 200)
        self.assertEqual(adopted["message"]["status"], "adopted")
        self.assertEqual(non_admin_export_status, 403)
        self.assertEqual(export_status, 200)
        self.assertEqual(export_headers.get("X-Export-Count"), "1")
        self.assertIn("feishu", export_headers.get("Content-Disposition", ""))
        self.assertTrue(export_body.startswith(b"PK"))
        with ZipFile(BytesIO(export_body)) as archive:
            names = set(archive.namelist())
            workbook_text = html.unescape("\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in names
                if name.endswith(".xml")
            ))
        self.assertIn("xl/media/image1.png", names)
        self.assertIn("已安排下周处理", workbook_text)
        self.assertNotIn("未采纳留言", workbook_text)
        self.assertEqual(other_export_status, 200)
        self.assertEqual(other_headers.get("X-Export-Count"), "0")
        self.assertNotIn("请导出截图".encode("utf-8"), other_body)

    @staticmethod
    def _request(port: int, method: str, path: str, user_id: str, tenant_id: str, payload: dict | None = None) -> tuple[int, dict]:
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

    @staticmethod
    def _request_bytes(port: int, method: str, path: str, user_id: str, tenant_id: str) -> tuple[int, bytes, dict[str, str]]:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
        connection.request(method, path, headers={"X-User-Id": user_id, "X-Tenant-Id": tenant_id})
        response = connection.getresponse()
        body = response.read()
        headers = {key: value for key, value in response.getheaders()}
        connection.close()
        return response.status, body, headers


if __name__ == "__main__":
    unittest.main()
