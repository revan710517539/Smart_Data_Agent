from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.platform.audit.store import sanitize_audit_detail
from backend.platform.storage import connect_sqlite


APPLICATION_MODULE_KEYS = {
    "dashboard",
    "business_funnel",
    "business_sandbox",
    "customer_insight",
    "single_customer_insight",
    "competition_analysis",
    "institution_supervision",
    "email_daily",
    "agent_workspace",
    "notifications",
    "weekly_report",
    "self_analysis",
    "platform_shell",
}


class UnsupportedApplicationAction(ValueError):
    pass


class ApplicationActionUnavailable(RuntimeError):
    pass


REGISTERED_ACTIONS: dict[str, set[str]] = {
    "dashboard": {"select_bank", "select_product", "open_insight_action"},
    "business_funnel": {"select_bank", "select_product_view", "export"},
    "business_sandbox": {"select_product_view", "run_simulation", "reset_simulation", "export"},
    "customer_insight": {"select_bank", "select_product_view", "select_segment"},
    "single_customer_insight": set(),
    "competition_analysis": {"select_product_view"},
    "institution_supervision": {"select_product_filter", "select_branch", "export"},
    "email_daily": {"generate_daily", "send_daily"},
    "agent_workspace": {
        "open_task", "configure_task", "open_task_composer", "open_todo_composer",
        "create_task", "update_task", "run_task", "analyze_insight", "mark_insight_read",
        "load_skill", "use_capability", "create_todo", "update_todo",
        "change_todo_status", "delete_todo",
    },
    "notifications": {"create_rule", "edit_rule", "toggle_rule", "manage_subscription", "mark_read", "acknowledge"},
    "weekly_report": {
        "save_version", "open_history", "open_export_dialog",
        "start_realtime_voice", "analyze_selected_context",
    },
    "self_analysis": {
        "upload_knowledge_file", "remove_knowledge_file", "select_analysis_skill",
        "clear_analysis_skill", "select_analysis_model", "cancel_auto_reference",
        "download_csv", "start_voice_input_fun_asr", "start_realtime_voice",
        "save_script", "run_script",
    },
    "platform_shell": {"select_institution", "select_quick_prompt", "ask_agent"},
}

UNAVAILABLE_ACTIONS = {
    ("business_funnel", "export"),
    ("business_sandbox", "run_simulation"),
    ("business_sandbox", "export"),
    ("institution_supervision", "export"),
    ("email_daily", "generate_daily"),
    ("email_daily", "send_daily"),
    ("agent_workspace", "run_task"),
    ("agent_workspace", "analyze_insight"),
    ("agent_workspace", "load_skill"),
    ("notifications", "create_rule"),
    ("notifications", "edit_rule"),
    ("notifications", "toggle_rule"),
    ("notifications", "manage_subscription"),
    ("weekly_report", "open_export_dialog"),
    ("self_analysis", "download_csv"),
    ("self_analysis", "save_script"),
    ("self_analysis", "run_script"),
    ("platform_shell", "ask_agent"),
}

STATE_ONLY_ACTIONS = {
    (module_key, action)
    for module_key, actions in REGISTERED_ACTIONS.items()
    for action in actions
    if (module_key, action) not in UNAVAILABLE_ACTIONS
}

DEFAULT_MODULE_STATES: dict[str, dict[str, Any]] = {
    "dashboard": {
        "exports": [],
        "actions": [],
        "selectedProduct": "all",
        "selectedBank": "全部分行",
    },
    "business_funnel": {
        "exports": [],
        "selectedBank": "全部分行",
        "productView": "compare",
    },
    "business_sandbox": {
        "exports": [],
        "lastSimulation": None,
        "simulationHistory": [],
    },
    "customer_insight": {
        "exports": [],
        "selectedBank": "全部分行",
        "selectedSegment": 0,
    },
    "single_customer_insight": {
        "exports": [],
        "serviceActions": [],
    },
    "competition_analysis": {
        "exports": [],
        "productView": "consumer",
    },
    "institution_supervision": {
        "exports": [],
        "selectedBranch": None,
        "productFilter": "all",
    },
    "email_daily": {
        "status": "draft",
        "generatedAt": "",
        "sentAt": "",
        "recipients": ["经营分析岗", "机构负责人", "风险策略岗"],
        "history": [],
    },
    "agent_workspace": {
        "createdTasks": [],
        "readInsightIds": [],
        "loadedSkills": [],
        "capabilityUsage": [],
        "todos": [],
    },
    "notifications": {
        "readIds": [],
        "acknowledgedIds": [],
        "subscriptionChanges": [],
    },
    "weekly_report": {
        "drafts": [],
        "exports": [],
        "historyOpenedAt": "",
    },
    "self_analysis": {
        "uploadedFiles": [],
        "downloads": [],
        "savedScripts": [],
    },
    "platform_shell": {
        "selectedInstitution": "上海分行",
        "agentMessages": [],
        "quickPrompts": [],
        "actions": [],
    },
}


class InMemoryApplicationStore:
    def __init__(self) -> None:
        self._states: dict[tuple[str, str], dict[str, Any]] = {}
        self._actions: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def get_module(self, tenant_id: str, module_key: str, actor_user_id: str | None = None) -> dict[str, Any]:
        module_key = _require_module_key(module_key)
        state = deepcopy(self._states.get((tenant_id, module_key)) or _default_state(module_key))
        actions = deepcopy(self._actions.get((tenant_id, module_key), []))[-50:]
        return _module_payload(tenant_id, module_key, state, actions, actor_user_id=actor_user_id)

    def run_action(
        self,
        tenant_id: str,
        module_key: str,
        action: str,
        payload: dict[str, Any] | None = None,
        actor_user_id: str | None = None,
        trusted_provenance: bool = False,
    ) -> dict[str, Any]:
        module_key = _require_module_key(module_key)
        action = _normalize_action(action)
        payload = dict(payload or {})
        state = deepcopy(self._states.get((tenant_id, module_key)) or _default_state(module_key))
        result, next_state = _execute_action(
            module_key,
            action,
            payload,
            state,
            actor_user_id=actor_user_id,
            trusted_provenance=trusted_provenance,
        )
        record = _action_record(module_key, action, payload, result, actor_user_id)
        self._states[(tenant_id, module_key)] = next_state
        self._actions.setdefault((tenant_id, module_key), []).append(record)
        return {
            "tenant_id": tenant_id,
            "module_key": module_key,
            "action": record,
            "result": result,
            "module": _module_payload(
                tenant_id,
                module_key,
                deepcopy(next_state),
                self._actions[(tenant_id, module_key)][-50:],
                actor_user_id=actor_user_id,
            ),
        }

    def close(self) -> None:
        return None


class SQLiteApplicationStore:
    def __init__(self, db_path: str | Path, initialize: bool = True) -> None:
        self.db_path = str(db_path)
        self._conn = connect_sqlite(self.db_path)
        self._conn.row_factory = sqlite3.Row
        if initialize:
            self.init_schema()

    def close(self) -> None:
        self._conn.close()

    def init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS platform_application_module_state (
                tenant_id TEXT NOT NULL,
                module_key TEXT NOT NULL,
                state_payload TEXT NOT NULL DEFAULT '{}',
                updated_by TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, module_key)
            );

            CREATE INDEX IF NOT EXISTS idx_platform_application_module_state
                ON platform_application_module_state(tenant_id, module_key);

            CREATE TABLE IF NOT EXISTS platform_application_actions (
                tenant_id TEXT NOT NULL,
                action_id TEXT NOT NULL,
                module_key TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                result TEXT NOT NULL DEFAULT '{}',
                created_by TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, action_id)
            );

            CREATE INDEX IF NOT EXISTS idx_platform_application_actions_tenant_module
                ON platform_application_actions(tenant_id, module_key, created_at DESC);
            """
        )
        self._conn.commit()

    def get_module(self, tenant_id: str, module_key: str, actor_user_id: str | None = None) -> dict[str, Any]:
        module_key = _require_module_key(module_key)
        state = self._load_state(tenant_id, module_key)
        actions = self._list_actions(tenant_id, module_key)
        return _module_payload(tenant_id, module_key, state, actions, actor_user_id=actor_user_id)

    def run_action(
        self,
        tenant_id: str,
        module_key: str,
        action: str,
        payload: dict[str, Any] | None = None,
        actor_user_id: str | None = None,
        trusted_provenance: bool = False,
    ) -> dict[str, Any]:
        module_key = _require_module_key(module_key)
        action = _normalize_action(action)
        payload = dict(payload or {})
        state = self._load_state(tenant_id, module_key)
        result, next_state = _execute_action(
            module_key,
            action,
            payload,
            state,
            actor_user_id=actor_user_id,
            trusted_provenance=trusted_provenance,
        )
        record = _action_record(module_key, action, payload, result, actor_user_id)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_application_module_state(
                    tenant_id, module_key, state_payload, updated_by, updated_at
                )
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(tenant_id, module_key) DO UPDATE SET
                    state_payload = excluded.state_payload,
                    updated_by = excluded.updated_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    tenant_id,
                    module_key,
                    json.dumps(next_state, ensure_ascii=False, sort_keys=True),
                    actor_user_id or "",
                ),
            )
            self._conn.execute(
                """
                INSERT INTO platform_application_actions(
                    tenant_id, action_id, module_key, action, status, payload, result, created_by, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    record["id"],
                    module_key,
                    action,
                    record["status"],
                    json.dumps(record["payload"], ensure_ascii=False, sort_keys=True),
                    json.dumps(record["result"], ensure_ascii=False, sort_keys=True),
                    actor_user_id or "",
                    record["createdAt"],
                ),
            )
        return {
            "tenant_id": tenant_id,
            "module_key": module_key,
            "action": record,
            "result": result,
            "module": _module_payload(
                tenant_id,
                module_key,
                deepcopy(next_state),
                self._list_actions(tenant_id, module_key),
                actor_user_id=actor_user_id,
            ),
        }

    def _load_state(self, tenant_id: str, module_key: str) -> dict[str, Any]:
        row = self._conn.execute(
            """
            SELECT state_payload
            FROM platform_application_module_state
            WHERE tenant_id = ? AND module_key = ?
            """,
            (tenant_id, module_key),
        ).fetchone()
        if not row:
            return _default_state(module_key)
        state = json.loads(row["state_payload"])
        if not isinstance(state, dict):
            return _default_state(module_key)
        return _merge_defaults(module_key, state)

    def _list_actions(self, tenant_id: str, module_key: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT action_id, module_key, action, status, payload, result, created_by, created_at
            FROM platform_application_actions
            WHERE tenant_id = ? AND module_key = ?
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (tenant_id, module_key),
        ).fetchall()
        return [
            {
                "id": row["action_id"],
                "moduleKey": row["module_key"],
                "action": row["action"],
                "status": row["status"],
                "payload": json.loads(row["payload"] or "{}"),
                "result": json.loads(row["result"] or "{}"),
                "createdBy": row["created_by"] or "",
                "createdAt": row["created_at"],
            }
            for row in rows
        ]


def _execute_action(
    module_key: str,
    action: str,
    payload: dict[str, Any],
    state: dict[str, Any],
    actor_user_id: str | None = None,
    trusted_provenance: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _require_registered_action(module_key, action)
    if (module_key, action) in UNAVAILABLE_ACTIONS:
        raise ApplicationActionUnavailable(
            f"Action {module_key}.{action} has no production handler and was not recorded as successful."
        )
    now = _now()
    next_state = _merge_defaults(module_key, state)
    if action.startswith("select_"):
        selection_keys = {
            "selectedBank",
            "selectedBranch",
            "selectedInstitution",
            "selectedProduct",
            "selectedSegment",
            "productView",
            "productFilter",
        }
        updated = {key: payload[key] for key in selection_keys if key in payload}
        next_state.update(updated)
        return {"message": "筛选条件已保存。", "selection": updated}, next_state

    if module_key == "business_sandbox" and action == "reset_simulation":
        next_state["lastSimulation"] = None
        return {"message": "模拟参数已重置。"}, next_state

    if module_key == "agent_workspace" and action == "create_task":
        task = _normalize_agent_task(_agent_task_action_payload(payload), now)
        task["ownerUserId"] = str(actor_user_id or "")
        task["createdBy"] = str(actor_user_id or "")
        next_state.setdefault("createdTasks", []).insert(0, task)
        next_state["createdTasks"] = next_state["createdTasks"][:30]
        return {"message": "自动化任务已创建。", "task": task}, next_state

    if module_key == "agent_workspace" and action == "update_task":
        task = _normalize_agent_task(_agent_task_action_payload(payload), now)
        tasks = [_normalize_agent_task(item, now) for item in next_state.get("createdTasks", []) if isinstance(item, dict)]
        for index, item in enumerate(tasks):
            if item["id"] == task["id"]:
                _require_task_mutation(item, actor_user_id)
                tasks[index] = {
                    **item,
                    **task,
                    "ownerUserId": item.get("ownerUserId") or actor_user_id or "",
                    "createdBy": item.get("createdBy") or actor_user_id or "",
                    "createdAt": item.get("createdAt") or task["createdAt"],
                }
                break
        else:
            raise KeyError("task_not_found")
        next_state["createdTasks"] = tasks[:30]
        return {"message": "任务已更新。", "task": task}, next_state

    if module_key == "agent_workspace" and action == "mark_insight_read":
        insight_id = str(payload.get("insightId") or payload.get("id") or "").strip()
        if insight_id:
            values = next_state.setdefault("readInsightIds", [])
            if insight_id not in values:
                values.append(insight_id)
        return {"message": "洞察已标记为已读。", "insightId": insight_id}, next_state

    if module_key == "agent_workspace" and action == "use_capability":
        usage = {"capability": str(payload.get("capability") or ""), "usedAt": now}
        next_state.setdefault("capabilityUsage", []).insert(0, usage)
        next_state["capabilityUsage"] = next_state["capabilityUsage"][:50]
        return {"message": "能力调用已记录。", "usage": usage}, next_state

    if module_key == "agent_workspace" and action == "create_todo":
        if not str((payload.get("todo") if isinstance(payload.get("todo"), dict) else payload).get("title") or "").strip():
            raise ValueError("todo_title_required")
        todo = _normalize_todo(
            payload.get("todo") if isinstance(payload.get("todo"), dict) else payload,
            now,
            default_owner_user_id=str(payload.get("ownerUserId") or ""),
        )
        todo["id"] = _id("todo")
        todo["ownerUserId"] = str(actor_user_id or "")
        todo["createdBy"] = str(actor_user_id or "")
        todo["assigneeUserId"] = str(actor_user_id or "")
        todo["assignee"] = str(actor_user_id or "当前用户")
        todo["source"] = _todo_source(todo.get("source")) if trusted_provenance else "manual"
        todo["createdAt"] = now
        todo["updatedAt"] = now
        if not trusted_provenance:
            todo["sourceVersionId"] = ""
            todo["sourceText"] = ""
            todo["background"] = ""
            todo["suggestion"] = ""
            todo["relatedOrg"] = ""
            todo["relatedMetric"] = ""
            todo["confidence"] = 0.0
        todos = _normalize_todos(next_state.get("todos"), now)
        todos.insert(0, todo)
        next_state["todos"] = todos[:200]
        return {"message": "待办任务已创建。", "todo": todo}, next_state

    if module_key == "agent_workspace" and action == "update_todo":
        todo = _normalize_todo(
            payload.get("todo") if isinstance(payload.get("todo"), dict) else payload,
            now,
            default_owner_user_id=str(payload.get("ownerUserId") or ""),
        )
        todos = _normalize_todos(next_state.get("todos"), now)
        updated = False
        for index, item in enumerate(todos):
            if item["id"] == todo["id"]:
                _require_todo_mutation(item, actor_user_id)
                todos[index] = {
                    **item,
                    "title": todo["title"],
                    "description": todo["description"],
                    "status": todo["status"],
                    "priority": todo["priority"],
                    "dueDate": todo["dueDate"],
                    "listName": todo["listName"],
                    "labels": todo["labels"],
                    "updatedAt": now,
                }
                updated = True
                break
        if not updated:
            raise KeyError("todo_not_found")
        next_state["todos"] = todos[:200]
        updated_todo = next(item for item in todos if item["id"] == todo["id"])
        return {"message": "待办任务已更新。", "todo": updated_todo}, next_state

    if module_key == "agent_workspace" and action == "change_todo_status":
        todo_id = str(payload.get("todoId") or payload.get("id") or "").strip()
        status = _todo_status(payload.get("status"))
        todos = _normalize_todos(next_state.get("todos"), now)
        for item in todos:
            if item["id"] == todo_id:
                _require_todo_mutation(item, actor_user_id)
                item["status"] = status
                item["updatedAt"] = now
                break
        else:
            raise KeyError("todo_not_found")
        next_state["todos"] = todos[:200]
        return {"message": "待办任务状态已更新。", "todoId": todo_id, "status": status}, next_state

    if module_key == "agent_workspace" and action == "delete_todo":
        todo_id = str(payload.get("todoId") or payload.get("id") or "").strip()
        todos = _normalize_todos(next_state.get("todos"), now)
        target = next((item for item in todos if item["id"] == todo_id), None)
        if target is None:
            raise KeyError("todo_not_found")
        _require_todo_mutation(target, actor_user_id, owner_only=True)
        next_state["todos"] = [item for item in todos if item["id"] != todo_id]
        return {"message": "待办任务已删除。", "todoId": todo_id}, next_state

    if module_key == "notifications" and action in {"mark_read", "acknowledge"}:
        item_id = str(payload.get("id") or payload.get("notificationId") or "").strip()
        key = "readIds" if action == "mark_read" else "acknowledgedIds"
        values = next_state.setdefault(key, [])
        if item_id and item_id not in values:
            values.append(item_id)
        return {"message": "通知状态已更新。", "id": item_id, "state": key}, next_state

    if module_key == "weekly_report" and action == "open_history":
        next_state["historyOpenedAt"] = now
        return {"message": "历史版本已打开。", "drafts": next_state.get("drafts", [])}, next_state

    if module_key == "self_analysis" and action == "upload_knowledge_file":
        file_id = str(payload.get("id") or "").strip()[:160]
        name = str(payload.get("name") or "").strip()[:240]
        if not file_id or not name:
            raise ValueError("knowledge_file_identity_required")
        uploaded = [item for item in next_state.get("uploadedFiles", []) if isinstance(item, dict) and item.get("id") != file_id]
        uploaded.insert(
            0,
            {
                "id": file_id,
                "name": name,
                "type": str(payload.get("type") or "")[:120],
                "size": max(0, int(payload.get("size") or 0)),
                "lastModified": max(0, int(payload.get("lastModified") or 0)),
                "uploadedAt": now,
            },
        )
        next_state["uploadedFiles"] = uploaded[:20]
        return {"message": "分析文件元数据已登记。", "file": uploaded[0]}, next_state

    if module_key == "self_analysis" and action == "remove_knowledge_file":
        file_id = str(payload.get("id") or payload.get("fileId") or "").strip()
        next_state["uploadedFiles"] = [
            item for item in next_state.get("uploadedFiles", []) if isinstance(item, dict) and item.get("id") != file_id
        ]
        return {"message": "分析文件登记已移除。", "fileId": file_id}, next_state

    if module_key == "platform_shell" and action == "select_quick_prompt":
        prompt = str(payload.get("prompt") or "").strip()
        if prompt:
            next_state.setdefault("quickPrompts", []).insert(0, {"prompt": prompt, "selectedAt": now})
            next_state["quickPrompts"] = next_state["quickPrompts"][:30]
        return {"message": "快捷问题已记录。", "prompt": prompt}, next_state

    if (module_key, action) in STATE_ONLY_ACTIONS:
        return {
            "message": "页面状态已同步。",
            "state_event": {"action": action, "recordedAt": now},
        }, next_state
    raise UnsupportedApplicationAction(f"unsupported application action: {module_key}.{action}")


def _normalize_todos(value: Any, now: str, default_owner_user_id: str = "") -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    todos: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        todo = _normalize_todo(item, now, default_owner_user_id=default_owner_user_id)
        if todo["id"] in seen:
            continue
        seen.add(todo["id"])
        todos.append(todo)
    return todos


def _normalize_todo(value: dict[str, Any], now: str, default_owner_user_id: str = "") -> dict[str, Any]:
    title = str(value.get("title") or "").strip()[:120]
    if not title:
        title = "未命名待办"
    todo_id = str(value.get("id") or _id("todo")).strip()[:80]
    return {
        "id": todo_id or _id("todo"),
        "title": title,
        "description": str(value.get("description") or "").strip()[:1000],
        "status": _todo_status(value.get("status")),
        "priority": _todo_priority(value.get("priority")),
        "dueDate": _todo_date(value.get("dueDate"), now),
        "assignee": str(value.get("assignee") or "当前用户").strip()[:80],
        "assigneeUserId": str(value.get("assigneeUserId") or default_owner_user_id or "").strip()[:80],
        "listName": str(value.get("listName") or "个人待办").strip()[:80],
        "labels": _string_list(value.get("labels"), limit=6, item_limit=30),
        "source": _todo_source(value.get("source")),
        "ownerUserId": str(value.get("ownerUserId") or default_owner_user_id or value.get("createdBy") or "").strip()[:80],
        "createdBy": str(value.get("createdBy") or "system").strip()[:80],
        "createdAt": str(value.get("createdAt") or now)[:40],
        "updatedAt": str(value.get("updatedAt") or now)[:40],
        "sourceVersionId": str(value.get("sourceVersionId") or value.get("source_version_id") or "").strip()[:120],
        "sourceText": str(value.get("sourceText") or value.get("source_text") or "").strip()[:1200],
        "background": str(value.get("background") or "").strip()[:1200],
        "suggestion": str(value.get("suggestion") or "").strip()[:1200],
        "relatedOrg": str(value.get("relatedOrg") or value.get("related_org") or "").strip()[:120],
        "relatedMetric": str(value.get("relatedMetric") or value.get("related_metric") or "").strip()[:120],
        "confidence": _todo_confidence(value.get("confidence")),
    }


def _todo_visible_to_user(todo: dict[str, Any], actor_user_id: str) -> bool:
    user_id = str(actor_user_id or "").strip()
    if not user_id:
        return True
    visible_values = {
        str(todo.get("ownerUserId") or "").strip(),
        str(todo.get("createdBy") or "").strip(),
        str(todo.get("assignee") or "").strip(),
        str(todo.get("assigneeUserId") or "").strip(),
    }
    return user_id in visible_values


def _normalize_agent_tasks(value: Any, now: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        task = _normalize_agent_task(item, now)
        if task["id"] in seen:
            continue
        seen.add(task["id"])
        tasks.append(task)
    return tasks


def _agent_task_action_payload(payload: dict[str, Any]) -> dict[str, Any]:
    task_payload = payload.get("task") if isinstance(payload.get("task"), dict) else payload
    task_payload = dict(task_payload)
    owner_user_id = str(payload.get("ownerUserId") or "").strip()
    if owner_user_id:
        task_payload.setdefault("ownerUserId", owner_user_id)
        task_payload.setdefault("createdBy", owner_user_id)
    return task_payload


def _normalize_agent_task(value: dict[str, Any], now: str) -> dict[str, Any]:
    task_id = str(value.get("id") or _id("task")).strip()[:80]
    category = str(value.get("category") or value.get("taskCategory") or value.get("kind") or "").strip()
    if category not in {"insight", "automation"}:
        category = "automation"
    name = str(value.get("name") or value.get("title") or "").strip()[:120]
    if not name:
        name = "新建任务触发洞察" if category == "insight" else "新建自动化任务"
    default_type = "任务触发洞察" if category == "insight" else "定时任务"
    owner_user_id = str(value.get("ownerUserId") or value.get("createdBy") or "").strip()[:80]
    created_by = str(value.get("createdBy") or owner_user_id or "system").strip()[:80]
    return {
        "id": task_id or _id("task"),
        "name": name,
        "category": category,
        "type": str(value.get("type") or default_type).strip()[:80],
        "schedule": str(value.get("schedule") or ("实时触发" if category == "insight" else "每日 09:00")).strip()[:120],
        "status": _agent_task_status(value.get("status")),
        "lastRun": str(value.get("lastRun") or value.get("last_run") or "未运行").strip()[:120],
        "result": str(value.get("result") or "").strip()[:500],
        "description": str(value.get("description") or "").strip()[:1200],
        "ownerUserId": owner_user_id,
        "createdBy": created_by,
        "createdAt": str(value.get("createdAt") or now)[:40],
        "updatedAt": str(value.get("updatedAt") or now)[:40],
    }


def _task_visible_to_user(task: dict[str, Any], actor_user_id: str) -> bool:
    user_id = str(actor_user_id or "").strip()
    if not user_id:
        return True
    visible_values = {
        str(task.get("ownerUserId") or "").strip(),
        str(task.get("createdBy") or "").strip(),
    }
    return not any(visible_values) or user_id in visible_values


def _require_todo_mutation(todo: dict[str, Any], actor_user_id: str | None, owner_only: bool = False) -> None:
    user_id = str(actor_user_id or "").strip()
    allowed = {
        str(todo.get("ownerUserId") or "").strip(),
        str(todo.get("createdBy") or "").strip(),
    }
    if not owner_only:
        allowed.add(str(todo.get("assigneeUserId") or "").strip())
    if not user_id or user_id not in allowed:
        raise PermissionError("todo_object_permission_denied")


def _require_task_mutation(task: dict[str, Any], actor_user_id: str | None) -> None:
    user_id = str(actor_user_id or "").strip()
    allowed = {
        str(task.get("ownerUserId") or "").strip(),
        str(task.get("createdBy") or "").strip(),
    }
    if not user_id or user_id not in allowed:
        raise PermissionError("task_object_permission_denied")


def _agent_task_status(value: Any) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized in {"running", "completed", "alert", "paused"} else "running"


def _todo_status(value: Any) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized in {"todo", "in_progress", "done", "closed"} else "todo"


def _todo_priority(value: Any) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized in {"low", "medium", "high", "urgent"} else "medium"


def _todo_source(value: Any) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized in {"manual", "system", "weekly_report", "agent"} else "manual"


def _todo_date(value: Any, now: str) -> str:
    text = str(value or "").strip()[:10]
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    return now[:10]


def _todo_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _string_list(value: Any, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = str(item or "").strip()[:item_limit]
        if text and text not in normalized:
            normalized.append(text)
        if len(normalized) >= limit:
            break
    return normalized


def _action_record(
    module_key: str,
    action: str,
    payload: dict[str, Any],
    result: dict[str, Any],
    actor_user_id: str | None,
) -> dict[str, Any]:
    return {
        "id": _id("act"),
        "moduleKey": module_key,
        "action": action,
        "status": "completed",
        "payload": sanitize_audit_detail(payload),
        "result": sanitize_audit_detail(result),
        "createdBy": actor_user_id or "",
        "createdAt": _now(),
    }


def _module_payload(
    tenant_id: str,
    module_key: str,
    state: dict[str, Any],
    actions: list[dict[str, Any]],
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    visible_state = _state_for_actor(module_key, state, actor_user_id)
    return {
        "tenant_id": tenant_id,
        "module_key": module_key,
        "state": _merge_defaults(module_key, visible_state),
        "actions": [
            action
            for action in actions
            if module_key != "agent_workspace" or not actor_user_id or action.get("createdBy") == actor_user_id
        ],
        "updated_at": _now(),
    }


def _state_for_actor(module_key: str, state: dict[str, Any], actor_user_id: str | None) -> dict[str, Any]:
    resolved = deepcopy(state)
    if module_key != "agent_workspace" or not actor_user_id:
        return resolved
    now = _now()
    legacy_seed_ids = {
        "todo_seed_weekly_balance",
        "todo_seed_m1_risk",
        "todo_seed_meeting_actions",
        "todo_seed_customer_manager",
    }
    resolved["todos"] = [
        todo
        for todo in _normalize_todos(resolved.get("todos"), now)
        if todo["id"] not in legacy_seed_ids and _todo_visible_to_user(todo, actor_user_id)
    ]
    resolved["createdTasks"] = [
        task for task in _normalize_agent_tasks(resolved.get("createdTasks"), now) if _task_visible_to_user(task, actor_user_id)
    ]
    return resolved


def _default_state(module_key: str) -> dict[str, Any]:
    return deepcopy(DEFAULT_MODULE_STATES.get(module_key, {}))


def _merge_defaults(module_key: str, state: dict[str, Any]) -> dict[str, Any]:
    merged = _default_state(module_key)
    merged.update(deepcopy(state))
    return merged


def _require_module_key(module_key: str) -> str:
    normalized = str(module_key or "").strip()
    if normalized not in APPLICATION_MODULE_KEYS:
        raise ValueError(f"unsupported application module: {normalized}")
    return normalized


def _normalize_action(action: str) -> str:
    normalized = str(action or "").strip()
    if not normalized:
        raise ValueError("action is required.")
    return normalized


def _require_registered_action(module_key: str, action: str) -> None:
    if action not in REGISTERED_ACTIONS.get(module_key, set()):
        raise UnsupportedApplicationAction(f"unsupported application action: {module_key}.{action}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id(prefix: str) -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
