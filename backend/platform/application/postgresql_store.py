from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import uuid4

from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.postgresql import PostgreSQLConnectionPool

from .store import (
    _action_record,
    _default_state,
    _execute_action,
    _merge_defaults,
    _module_payload,
    _normalize_action,
    _require_module_key,
)

SHARED_PAGE_LAYOUT_MODULES = frozenset({"dashboard", "institution_supervision"})


def _shared_page_layout_module(module_key: str) -> bool:
    return module_key in SHARED_PAGE_LAYOUT_MODULES


class PostgreSQLApplicationStore:
    """Production page state; core todos/tasks are projected from normalized tables."""

    def __init__(self, pool: PostgreSQLConnectionPool, *, owns_pool: bool = False) -> None:
        self.pool = pool
        self.owns_pool = owns_pool

    def close(self) -> None:
        if self.owns_pool:
            self.pool.close()

    def get_module(self, tenant_id: str, module_key: str, actor_user_id: str | None = None) -> dict[str, Any]:
        module_key = _require_module_key(module_key)
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, actor_user_id, required=False) if actor_user_id else None
            state = self._load_state(connection, tenant_key, module_key, actor_key)
            if _shared_page_layout_module(module_key):
                shared_state = self._load_state(connection, tenant_key, module_key, None)
                state["pageDataLayout"] = list(shared_state.get("pageDataLayout") or [])
                state["pageDataNotes"] = list(shared_state.get("pageDataNotes") or [])
                state["pageStickyNote"] = dict(shared_state.get("pageStickyNote") or {})
            if module_key == "agent_workspace":
                state["todos"] = self._todos(connection, tenant_key, actor_key)
                state["createdTasks"] = self._tasks(connection, tenant_key, actor_key)
            actions = self._actions(connection, tenant_key, module_key, actor_key)
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
        if not actor_user_id:
            raise ValueError("application_action_actor_required")
        payload = dict(payload or {})
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, actor_user_id)
            state = self._load_state(connection, tenant_key, module_key, actor_key)
            if _shared_page_layout_module(module_key):
                shared_state = self._load_state(connection, tenant_key, module_key, None)
                state["pageDataLayout"] = list(shared_state.get("pageDataLayout") or [])
                state["pageDataNotes"] = list(shared_state.get("pageDataNotes") or [])
                state["pageStickyNote"] = dict(shared_state.get("pageStickyNote") or {})
            if module_key == "agent_workspace":
                state["todos"] = self._todos(connection, tenant_key, actor_key)
                state["createdTasks"] = self._tasks(connection, tenant_key, actor_key)
            result, next_state = _execute_action(
                module_key,
                action,
                payload,
                deepcopy(state),
                actor_user_id=actor_user_id,
                trusted_provenance=trusted_provenance,
            )
            handler_ref = "application.state"
            if module_key == "agent_workspace" and action in {"create_todo", "update_todo", "change_todo_status", "delete_todo"}:
                handler_ref = "application.todo"
                self._persist_todo_action(connection, tenant_key, actor_key, action, result, payload)
                next_state["todos"] = self._todos(connection, tenant_key, actor_key)
            elif module_key == "agent_workspace" and action in {"create_task", "update_task"}:
                handler_ref = "application.automation_draft"
                self._persist_task_draft(connection, tenant_key, actor_key, action, result)
                next_state["createdTasks"] = self._tasks(connection, tenant_key, actor_key)
            if _shared_page_layout_module(module_key) and action in {"set_page_data_layout", "set_page_data_notes", "set_page_sticky_note"}:
                shared_state = self._load_state(connection, tenant_key, module_key, None)
                if action == "set_page_data_layout":
                    shared_state["pageDataLayout"] = list(next_state.get("pageDataLayout") or [])
                    shared_state["pageDataNotes"] = list(next_state.get("pageDataNotes") or [])
                if action == "set_page_data_notes":
                    shared_state["pageDataNotes"] = list(next_state.get("pageDataNotes") or [])
                if action == "set_page_sticky_note":
                    shared_state["pageStickyNote"] = dict(next_state.get("pageStickyNote") or {})
                self._save_non_core_state(
                    connection, tenant_key, module_key, None, shared_state,
                    created_by_key=actor_key,
                )
            else:
                self._save_non_core_state(
                    connection, tenant_key, module_key, actor_key, next_state,
                    created_by_key=actor_key,
                )
            record = _action_record(module_key, action, payload, result, actor_user_id)
            self._record_action(connection, tenant_key, actor_key, record, handler_ref)
            actions = self._actions(connection, tenant_key, module_key, actor_key)
        return {
            "tenant_id": tenant_id,
            "module_key": module_key,
            "action": record,
            "result": result,
            "module": _module_payload(tenant_id, module_key, next_state, actions, actor_user_id=actor_user_id),
        }

    @staticmethod
    def _load_state(connection: Any, tenant_key: Any, module_key: str, actor_key: Any | None) -> dict[str, Any]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT state_value FROM platform_application_module_state
                WHERE tenant_id=%s AND module_code=%s AND owner_user_id IS NOT DISTINCT FROM %s AND state_key='state'
                ORDER BY updated_at DESC LIMIT 1
                """,
                (tenant_key, module_key, actor_key),
            )
            row = cursor.fetchone()
        if not row:
            return _default_state(module_key)
        value = _json_value(_value(row, "state_value", 0), {})
        return _merge_defaults(module_key, value if isinstance(value, dict) else {})

    @staticmethod
    def _save_non_core_state(
        connection: Any,
        tenant_key: Any,
        module_key: str,
        owner_key: Any | None,
        state: dict[str, Any],
        *,
        created_by_key: Any,
    ) -> None:
        clean = deepcopy(state)
        if module_key == "agent_workspace":
            clean.pop("todos", None)
            clean.pop("createdTasks", None)
        with connection.cursor() as cursor:
            # Serialize the first write as well as subsequent row updates.  A row
            # lock alone cannot protect the "no row yet" case, so two workers
            # opening a module for the first time could otherwise race on the
            # expression-based unique index.
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"application-state:{tenant_key}:{module_key}:{owner_key}",),
            )
            cursor.execute(
                """
                SELECT module_state_id FROM platform_application_module_state
                WHERE tenant_id=%s AND module_code=%s AND owner_user_id IS NOT DISTINCT FROM %s AND state_key='state'
                FOR UPDATE
                """,
                (tenant_key, module_key, owner_key),
            )
            row = cursor.fetchone()
            if row:
                cursor.execute(
                    "UPDATE platform_application_module_state SET state_value=%s::jsonb,updated_at=now(),lock_version=lock_version+1 WHERE module_state_id=%s",
                    (_json(clean), _value(row, "module_state_id", 0)),
                )
            else:
                cursor.execute(
                    "INSERT INTO platform_application_module_state(tenant_id,module_code,owner_user_id,state_key,state_value,created_by) VALUES (%s,%s,%s,'state',%s::jsonb,%s)",
                    (tenant_key, module_key, owner_key, _json(clean), created_by_key),
                )

    @staticmethod
    def _record_action(connection: Any, tenant_key: Any, actor_key: Any, record: dict[str, Any], handler_ref: str) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO platform_application_actions(
                    tenant_id,application_action_key,module_code,action_code,actor_user_id,
                    idempotency_key,request_payload,status,handler_ref,result_ref,finished_at,created_by
                ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,'succeeded',%s,%s::jsonb,now(),%s)
                """,
                (
                    tenant_key, record["id"], record["moduleKey"], record["action"], actor_key,
                    record["id"], _json(record["payload"]), handler_ref, _json(record["result"]), actor_key,
                ),
            )

    @staticmethod
    def _actions(connection: Any, tenant_key: Any, module_key: str, actor_key: Any | None) -> list[dict[str, Any]]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT a.application_action_key AS id,a.module_code,a.action_code,a.status,
                       a.request_payload,a.result_ref,u.external_subject AS created_by,a.created_at
                FROM platform_application_actions a
                JOIN platform_user_profiles u ON u.user_id=a.actor_user_id
                WHERE a.tenant_id=%s AND a.module_code=%s
                """ + (" AND a.actor_user_id=%s" if actor_key else "") + " ORDER BY a.created_at DESC LIMIT 50",
                (tenant_key, module_key, actor_key) if actor_key else (tenant_key, module_key),
            )
            rows = cursor.fetchall()
        return [
            {
                "id": str(_value(row, "id", 0)),
                "moduleKey": str(_value(row, "module_code", 1)),
                "action": str(_value(row, "action_code", 2)),
                "status": "completed" if str(_value(row, "status", 3)) == "succeeded" else str(_value(row, "status", 3)),
                "payload": _json_value(_value(row, "request_payload", 4), {}),
                "result": _json_value(_value(row, "result_ref", 5), {}),
                "createdBy": str(_value(row, "created_by", 6)),
                "createdAt": _iso(_value(row, "created_at", 7)),
            }
            for row in rows
        ]

    def _persist_todo_action(self, connection: Any, tenant_key: Any, actor_key: Any, action: str, result: dict[str, Any], payload: dict[str, Any]) -> None:
        if action == "delete_todo":
            todo_id = str(result["todoId"])
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_todos SET status='cancelled',result_summary='{"deleted":true}'::jsonb,
                        updated_at=now(),lock_version=lock_version+1
                    WHERE tenant_id=%s AND todo_key=%s AND owner_user_id=%s
                    """,
                    (tenant_key, todo_id, actor_key),
                )
                if cursor.rowcount != 1:
                    raise KeyError("todo_not_found")
            return
        if action == "change_todo_status":
            todo_id = str(result["todoId"])
            status = _todo_status_db(str(result["status"]))
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_todos SET status=%s,completed_at=CASE WHEN %s='completed' THEN now() END,
                        updated_at=now(),lock_version=lock_version+1
                    WHERE tenant_id=%s AND todo_key=%s AND (owner_user_id=%s OR assignee_user_id=%s)
                    """,
                    (status, status, tenant_key, todo_id, actor_key, actor_key),
                )
                if cursor.rowcount != 1:
                    raise KeyError("todo_not_found")
            return
        todo = dict(result.get("todo") or {})
        todo_id = str(todo.get("id") or "").strip()
        if not todo_id:
            raise ValueError("todo_id_required")
        assignee_external = str(todo.get("assigneeUserId") or todo.get("ownerUserId") or "").strip()
        assignee_key = PostgreSQLIdentityResolver.user_id(connection, assignee_external, required=False) or actor_key
        metadata = {
            key: todo.get(key)
            for key in (
                "assignee", "listName", "labels", "sourceVersionId", "sourceText", "background",
                "suggestion", "relatedOrg", "relatedMetric", "confidence", "createdAt", "updatedAt",
            )
            if todo.get(key) not in (None, "")
        }
        source = str(todo.get("source") or "manual")
        due_at = _due(todo.get("dueDate"))
        with connection.cursor() as cursor:
            if action == "update_todo":
                cursor.execute(
                    "SELECT owner_user_id,assignee_user_id FROM platform_todos WHERE tenant_id=%s AND todo_key=%s FOR UPDATE",
                    (tenant_key, todo_id),
                )
                existing = cursor.fetchone()
                if not existing:
                    raise KeyError("todo_not_found")
                # Authorization is based on the persisted object.  Never trust
                # the requested assignee: otherwise a caller could assign the
                # object to themselves and use that forged value as permission.
                existing_owner = _value(existing, "owner_user_id", 0)
                existing_assignee = _value(existing, "assignee_user_id", 1)
                if existing_owner != actor_key and existing_assignee != actor_key:
                    raise PermissionError("todo_object_permission_denied")
            cursor.execute(
                """
                INSERT INTO platform_todos(
                    tenant_id,todo_key,title,description,owner_user_id,assignee_user_id,
                    source_type,priority,status,due_at,completed_at,result_summary,todo_metadata,created_by
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CASE WHEN %s='completed' THEN now() END,'{}'::jsonb,%s::jsonb,%s)
                ON CONFLICT (tenant_id,todo_key) DO UPDATE SET
                    title=EXCLUDED.title,description=EXCLUDED.description,assignee_user_id=EXCLUDED.assignee_user_id,
                    priority=EXCLUDED.priority,status=EXCLUDED.status,due_at=EXCLUDED.due_at,
                    completed_at=EXCLUDED.completed_at,todo_metadata=EXCLUDED.todo_metadata,
                    updated_at=now(),lock_version=platform_todos.lock_version+1
                """,
                (
                    tenant_key,todo_id,str(todo.get("title") or "")[:500],str(todo.get("description") or ""),
                    actor_key,assignee_key,source,_priority(todo.get("priority")),_todo_status_db(str(todo.get("status") or "todo")),
                    due_at,_todo_status_db(str(todo.get("status") or "todo")),_json(metadata),actor_key,
                ),
            )

    @staticmethod
    def _persist_task_draft(connection: Any, tenant_key: Any, actor_key: Any, action: str, result: dict[str, Any]) -> None:
        task = dict(result.get("task") or {})
        task_key = str(task.get("id") or "").strip()
        if not task_key:
            raise ValueError("automation_task_id_required")
        schedule = str(task.get("schedule") or "").strip()
        config = {**task, "draft": True, "source": "agent_workspace"}
        with connection.cursor() as cursor:
            if action == "update_task":
                cursor.execute("SELECT owner_user_id FROM platform_automation_tasks WHERE tenant_id=%s AND automation_task_key=%s FOR UPDATE", (tenant_key, task_key))
                existing = cursor.fetchone()
                if not existing:
                    raise KeyError("task_not_found")
                if _value(existing, "owner_user_id", 0) != actor_key:
                    raise PermissionError("task_object_permission_denied")
            cursor.execute(
                """
                INSERT INTO platform_automation_tasks(
                    tenant_id,automation_task_key,task_code,task_name,task_type,trigger_type,
                    handler_ref,task_config,retry_policy,timeout_seconds,max_concurrency,status,
                    owner_user_id,created_by
                ) VALUES (%s,%s,%s,%s,'custom','manual','application.draft',%s::jsonb,'{}'::jsonb,900,1,'paused',%s,%s)
                ON CONFLICT (tenant_id,automation_task_key) DO UPDATE SET
                    task_name=EXCLUDED.task_name,task_config=EXCLUDED.task_config,status='paused',
                    updated_at=now(),lock_version=platform_automation_tasks.lock_version+1
                """,
                (tenant_key,task_key,task_key,str(task.get("name") or task_key)[:300],_json({**config,"schedule":schedule}),actor_key,actor_key),
            )

    @staticmethod
    def _todos(connection: Any, tenant_key: Any, actor_key: Any | None) -> list[dict[str, Any]]:
        if actor_key is None:
            return []
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.todo_key,t.title,t.description,t.status,t.priority,t.due_at,
                       owner.external_subject AS owner_user_id,assignee.external_subject AS assignee_user_id,
                       assignee.display_name AS assignee_name,t.source_type,t.todo_metadata,t.created_at,t.updated_at
                FROM platform_todos t
                JOIN platform_user_profiles owner ON owner.user_id=t.owner_user_id
                JOIN platform_user_profiles assignee ON assignee.user_id=t.assignee_user_id
                WHERE t.tenant_id=%s AND (t.owner_user_id=%s OR t.assignee_user_id=%s)
                  AND NOT (t.status='cancelled' AND COALESCE((t.result_summary->>'deleted')::boolean,false))
                ORDER BY t.updated_at DESC LIMIT 200
                """,
                (tenant_key,actor_key,actor_key),
            )
            rows=cursor.fetchall()
        result=[]
        for row in rows:
            metadata=_json_value(_value(row,"todo_metadata",10),{})
            owner=str(_value(row,"owner_user_id",6))
            assignee=str(_value(row,"assignee_user_id",7))
            assignee_name=str(_value(row,"assignee_name",8) or "").strip()
            result.append({
                "id":str(_value(row,"todo_key",0)),"title":str(_value(row,"title",1)),"description":str(_value(row,"description",2)),
                "status":_todo_status_ui(str(_value(row,"status",3))),"priority":str(_value(row,"priority",4)),
                "dueDate":_date_text(_value(row,"due_at",5)),"assignee":assignee_name or "未知用户",
                "assigneeUserId":assignee,"listName":str(metadata.get("listName") or "个人待办"),
                "labels":metadata.get("labels") if isinstance(metadata.get("labels"),list) else [],"source":str(_value(row,"source_type",9) or "manual"),
                "ownerUserId":owner,"createdBy":owner,"createdAt":str(metadata.get("createdAt") or _iso(_value(row,"created_at",11))),
                "updatedAt":_iso(_value(row,"updated_at",12)),
                **{key:metadata.get(key) for key in ("sourceVersionId","sourceText","background","suggestion","relatedOrg","relatedMetric","confidence") if key in metadata},
            })
        return result

    @staticmethod
    def _tasks(connection: Any, tenant_key: Any, actor_key: Any | None) -> list[dict[str, Any]]:
        if actor_key is None:
            return []
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.automation_task_key,t.task_name,t.task_config,t.status,t.created_at,t.updated_at
                FROM platform_automation_tasks t
                WHERE t.tenant_id=%s AND t.owner_user_id=%s AND t.handler_ref='application.draft'
                ORDER BY t.updated_at DESC LIMIT 30
                """,
                (tenant_key,actor_key),
            )
            rows=cursor.fetchall()
        result=[]
        for row in rows:
            config=_json_value(_value(row,"task_config",2),{})
            result.append({**config,"id":str(_value(row,"automation_task_key",0)),"name":str(_value(row,"task_name",1)),
                "status":str(config.get("status") or ("paused" if str(_value(row,"status",3))=="paused" else "running")),
                "createdAt":str(config.get("createdAt") or _iso(_value(row,"created_at",4))),"updatedAt":_iso(_value(row,"updated_at",5))})
        return result

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self.pool.connection() as connection:
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise


def _todo_status_db(value: str) -> str:
    return {"todo":"open","in_progress":"in_progress","done":"completed","closed":"cancelled"}.get(value,"open")


def _todo_status_ui(value: str) -> str:
    return {"open":"todo","in_progress":"in_progress","blocked":"in_progress","completed":"done","cancelled":"closed"}.get(value,"todo")


def _priority(value: Any) -> str:
    text=str(value or "medium")
    return text if text in {"low","medium","high","urgent"} else "medium"


def _due(value: Any) -> datetime:
    text=str(value or "")[:10]
    try:
        parsed=datetime.fromisoformat(text)
    except ValueError:
        parsed=datetime.now(timezone.utc)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _date_text(value: Any) -> str:
    if isinstance(value,datetime): return value.date().isoformat()
    return str(value or "")[:10]


def _json_value(value: Any, default: Any) -> Any:
    if value is None:return default
    if isinstance(value,(dict,list)):return value
    try:return json.loads(value)
    except (TypeError,json.JSONDecodeError):return default


def _value(row:Any,key:str,index:int)->Any:
    if isinstance(row,dict):return row[key]
    try:return row[key]
    except (TypeError,KeyError,IndexError):return row[index]


def _json(value:Any)->str:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,default=str,separators=(",",":"))


def _iso(value:Any)->str:
    return value.isoformat() if isinstance(value,datetime) else str(value or "")
