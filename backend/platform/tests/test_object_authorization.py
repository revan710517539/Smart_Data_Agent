from __future__ import annotations

import unittest

from backend.platform.application import InMemoryApplicationStore
from backend.platform.reports import InMemoryReportStore


class ObjectAuthorizationTest(unittest.TestCase):
    def test_saved_analysis_defaults_private_and_owner_controls_update_delete(self) -> None:
        store = InMemoryReportStore()
        saved = store.upsert_analysis_result(
            "tenant_demo",
            {
                "id": "saved_private",
                "title": "个人分析",
                "query": "query",
                "analysisTaskId": "task_owned",
                "rows": [{"secret": "must_not_be_copied"}],
            },
            updated_by="u_owner",
        )
        self.assertEqual(saved["visibility"], "private")
        self.assertEqual(saved["rows"], [])
        self.assertEqual(store.list_analysis_results("tenant_demo", "u_attacker"), [])
        with self.assertRaises(PermissionError):
            store.upsert_analysis_result(
                "tenant_demo",
                {"id": "saved_private", "title": "篡改", "analysisTaskId": "task_owned"},
                updated_by="u_attacker",
            )
        with self.assertRaises(PermissionError):
            store.delete_analysis_result("tenant_demo", "saved_private", actor_user_id="u_attacker")
        self.assertTrue(store.delete_analysis_result("tenant_demo", "saved_private", actor_user_id="u_owner"))

    def test_todo_owner_cannot_be_spoofed_and_other_user_cannot_mutate(self) -> None:
        store = InMemoryApplicationStore()
        created = store.run_action(
            "tenant_demo",
            "agent_workspace",
            "create_todo",
            payload={
                "ownerUserId": "u_victim",
                "todo": {
                    "id": "todo_private",
                    "title": "个人待办",
                    "ownerUserId": "u_victim",
                    "assigneeUserId": "u_victim",
                    "source": "system",
                    "createdAt": "2000-01-01T00:00:00Z",
                    "updatedAt": "2000-01-01T00:00:00Z",
                },
            },
            actor_user_id="u_owner",
        )
        todo = created["result"]["todo"]
        self.assertEqual(todo["ownerUserId"], "u_owner")
        self.assertEqual(todo["createdBy"], "u_owner")
        self.assertEqual(todo["assigneeUserId"], "u_owner")
        self.assertNotEqual(todo["id"], "todo_private")
        self.assertEqual(todo["source"], "manual")
        self.assertNotEqual(todo["createdAt"], "2000-01-01T00:00:00Z")
        todo_id = todo["id"]
        self.assertEqual(store.get_module("tenant_demo", "agent_workspace", "u_victim")["state"]["todos"], [])

        for action, payload in (
            ("update_todo", {"todo": {"id": todo_id, "title": "篡改"}}),
            ("change_todo_status", {"todoId": todo_id, "status": "done"}),
            ("delete_todo", {"todoId": todo_id}),
        ):
            with self.subTest(action=action), self.assertRaises(PermissionError):
                store.run_action(
                    "tenant_demo",
                    "agent_workspace",
                    action,
                    payload=payload,
                    actor_user_id="u_attacker",
                )

        updated = store.run_action(
            "tenant_demo",
            "agent_workspace",
            "change_todo_status",
            payload={"todoId": todo_id, "status": "done"},
            actor_user_id="u_owner",
        )
        self.assertEqual(updated["result"]["status"], "done")

    def test_automation_task_update_requires_object_owner(self) -> None:
        store = InMemoryApplicationStore()
        store.run_action(
            "tenant_demo",
            "agent_workspace",
            "create_task",
            payload={"task": {"id": "task_private", "name": "私有任务", "ownerUserId": "u_other"}},
            actor_user_id="u_owner",
        )
        with self.assertRaises(PermissionError):
            store.run_action(
                "tenant_demo",
                "agent_workspace",
                "update_task",
                payload={"task": {"id": "task_private", "name": "攻击者修改"}},
                actor_user_id="u_attacker",
            )
        visible = store.get_module("tenant_demo", "agent_workspace", "u_owner")
        self.assertEqual(visible["state"]["createdTasks"][0]["name"], "私有任务")


if __name__ == "__main__":
    unittest.main()
