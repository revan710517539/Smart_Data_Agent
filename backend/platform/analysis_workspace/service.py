from __future__ import annotations

import hashlib
import hmac
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from backend.platform.database.mysql import MySQLConnectionPool

from .models import AnalysisWorkspaceContext


THREAD_STATUSES = {"active", "merged", "archived"}
TURN_STATUSES = {"clarification", "queued", "running", "completed", "partial", "failed", "cancelled"}


class AnalysisWorkspaceStore(Protocol):
    def upsert_workspace(self, tenant_id: str, user_id: str, workspace_key: str, context: dict[str, Any]) -> dict[str, Any]: ...
    def get_workspace(self, tenant_id: str, user_id: str, workspace_id: str) -> dict[str, Any] | None: ...
    def list_threads(self, tenant_id: str, user_id: str, workspace_id: str) -> list[dict[str, Any]]: ...
    def create_thread(self, tenant_id: str, user_id: str, workspace_id: str, parent_thread_id: str | None, title: str, anchor: dict[str, Any]) -> dict[str, Any]: ...
    def append_turn(self, tenant_id: str, user_id: str, thread_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def merge_threads(self, tenant_id: str, user_id: str, target_thread_id: str, source_thread_ids: list[str], question: str, answer: str, evidence_refs: list[dict[str, Any]]) -> dict[str, Any]: ...


class AnalysisWorkspaceService:
    def __init__(self, store: AnalysisWorkspaceStore) -> None:
        self.store = store

    def ensure_workspace(self, tenant_id: str, user_id: str, workspace_key: str, context: AnalysisWorkspaceContext) -> dict[str, Any]:
        key = _required(workspace_key, "workspace_key")
        if context.page_key != key and not key.startswith(context.page_key + ":"):
            raise ValueError("workspace_page_key_mismatch")
        return self.store.upsert_workspace(tenant_id, user_id, key, context.payload())

    def workspace(self, tenant_id: str, user_id: str, workspace_id: str) -> dict[str, Any]:
        workspace = self.store.get_workspace(tenant_id, user_id, _required(workspace_id, "workspace_id"))
        if workspace is None:
            raise PermissionError("analysis_workspace_not_owned")
        return workspace

    def threads(self, tenant_id: str, user_id: str, workspace_id: str) -> list[dict[str, Any]]:
        self.workspace(tenant_id, user_id, workspace_id)
        return self.store.list_threads(tenant_id, user_id, workspace_id)

    def branch(self, tenant_id: str, user_id: str, workspace_id: str, *, parent_thread_id: str | None, title: str, anchor: dict[str, Any] | None = None) -> dict[str, Any]:
        self.workspace(tenant_id, user_id, workspace_id)
        return self.store.create_thread(tenant_id, user_id, workspace_id, parent_thread_id, title[:240], _bounded_object(anchor))

    def append_turn(self, tenant_id: str, user_id: str, thread_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        question = _required(payload.get("question"), "question")
        status = str(payload.get("status") or "completed")
        if status not in TURN_STATUSES:
            raise ValueError("analysis_turn_status_invalid")
        normalized = {
            "question": question[:20_000],
            "answer": str(payload.get("answer") or "")[:100_000],
            "intent": _bounded_object(payload.get("intent")),
            "execution_plan": _bounded_object(payload.get("execution_plan")),
            "artifact_refs": _bounded_list(payload.get("artifact_refs")),
            "evidence_refs": _bounded_list(payload.get("evidence_refs")),
            "status": status,
        }
        return self.store.append_turn(tenant_id, user_id, _required(thread_id, "thread_id"), normalized)

    def merge(self, tenant_id: str, user_id: str, target_thread_id: str, source_thread_ids: list[str], *, question: str, answer: str, evidence_refs: list[dict[str, Any]]) -> dict[str, Any]:
        sources = list(dict.fromkeys(_required(item, "source_thread_id") for item in source_thread_ids))
        if not sources or target_thread_id in sources:
            raise ValueError("analysis_thread_merge_sources_invalid")
        return self.store.merge_threads(
            tenant_id,
            user_id,
            _required(target_thread_id, "target_thread_id"),
            sources,
            _required(question, "question")[:20_000],
            _required(answer, "answer")[:100_000],
            _bounded_list(evidence_refs),
        )


class InMemoryAnalysisGovernanceStore:
    """Local/test cache index with the same fail-closed contract as MySQL."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = RLock()

    def get_cache(self, tenant_id: str, user_id: str, cache_key: str, authorization_hash: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._cache.get((tenant_id, cache_key))
            if not item or item["owner_user_id"] != user_id or item["authorization_hash"] != authorization_hash:
                return None
            if item.get("invalidated_at") or datetime.fromisoformat(item["expires_at"]) <= datetime.now(timezone.utc):
                return None
            return deepcopy(item)

    def put_cache(self, tenant_id: str, user_id: str, payload: dict[str, Any], ttl_seconds: int = 900) -> dict[str, Any]:
        with self._lock:
            item = {
                **deepcopy(payload),
                "tenant_id": tenant_id,
                "owner_user_id": user_id,
                "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=max(60, min(ttl_seconds, 3600)))).isoformat(),
                "invalidated_at": None,
            }
            self._cache[(tenant_id, payload["cache_key"])] = item
            return deepcopy(item)


class MySQLAnalysisGovernanceStore:
    """Permission-bound result cache index over the MySQL primary."""

    def __init__(self, pool: MySQLConnectionPool) -> None:
        self.pool = pool

    def get_cache(self, tenant_id: str, user_id: str, cache_key: str, authorization_hash: str) -> dict[str, Any] | None:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            tenant_key, user_key = _resolve_identity(cursor, tenant_id, user_id)
            cursor.execute(
                """
                SELECT cache_key,authorization_hash,csv_snapshot_hash,semantic_version_hash,
                       execution_version_hash,result_ref,expires_at,invalidated_at,invalidation_reason,
                       created_at,updated_at
                FROM platform_analysis_result_cache
                WHERE tenant_id=%s AND owner_user_id=%s AND cache_key=%s
                  AND authorization_hash=%s AND invalidated_at IS NULL
                  AND expires_at>UTC_TIMESTAMP(6)
                """,
                (tenant_key, user_key, cache_key, authorization_hash),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def put_cache(self, tenant_id: str, user_id: str, payload: dict[str, Any], ttl_seconds: int = 900) -> dict[str, Any]:
        ttl = max(60, min(int(ttl_seconds), 3600))
        with self.pool.transaction() as connection, connection.cursor() as cursor:
            tenant_key, user_key = _resolve_identity(cursor, tenant_id, user_id)
            cursor.execute(
                """
                INSERT INTO platform_analysis_result_cache(
                    tenant_id,cache_key,owner_user_id,authorization_hash,csv_snapshot_hash,
                    semantic_version_hash,execution_version_hash,result_ref,expires_at,created_by
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,DATE_ADD(UTC_TIMESTAMP(6),INTERVAL %s SECOND),%s)
                ON DUPLICATE KEY UPDATE
                    owner_user_id=VALUES(owner_user_id),authorization_hash=VALUES(authorization_hash),
                    csv_snapshot_hash=VALUES(csv_snapshot_hash),semantic_version_hash=VALUES(semantic_version_hash),
                    execution_version_hash=VALUES(execution_version_hash),result_ref=VALUES(result_ref),
                    expires_at=VALUES(expires_at),invalidated_at=NULL,invalidation_reason='',
                    updated_at=UTC_TIMESTAMP(6),lock_version=lock_version+1
                """,
                (
                    tenant_key, payload["cache_key"], user_key, payload["authorization_hash"],
                    payload["csv_snapshot_hash"], payload["semantic_version_hash"],
                    payload["execution_version_hash"], payload["result_ref"], ttl, user_key,
                ),
            )
        return self.get_cache(tenant_id, user_id, payload["cache_key"], payload["authorization_hash"]) or {}


class InMemoryAnalysisWorkspaceStore:
    """Test-only store; persistent runtimes bind MySQLAnalysisWorkspaceStore."""

    def __init__(self) -> None:
        self.workspaces: dict[str, dict[str, Any]] = {}
        self.threads: dict[str, dict[str, Any]] = {}
        self.turns: dict[str, list[dict[str, Any]]] = {}
        self._lock = RLock()

    def upsert_workspace(self, tenant_id: str, user_id: str, workspace_key: str, context: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            existing = next((item for item in self.workspaces.values() if item["tenant_id"] == tenant_id and item["workspace_key"] == workspace_key), None)
            if existing and existing["owner_user_id"] != user_id:
                raise PermissionError("analysis_workspace_not_owned")
            workspace = existing or {
                "workspace_id": f"ws_{uuid4().hex}",
                "tenant_id": tenant_id,
                "owner_user_id": user_id,
                "workspace_key": workspace_key,
                "created_at": _now(),
            }
            workspace.update({"page_key": context["page_key"], "artifact_ref": context.get("artifact_id", ""), "context_snapshot": deepcopy(context), "status": "active", "updated_at": _now()})
            self.workspaces[workspace["workspace_id"]] = workspace
            if not any(thread["workspace_id"] == workspace["workspace_id"] for thread in self.threads.values()):
                self.create_thread(tenant_id, user_id, workspace["workspace_id"], None, "总体分析", {})
            return deepcopy(workspace)

    def get_workspace(self, tenant_id: str, user_id: str, workspace_id: str) -> dict[str, Any] | None:
        workspace = self.workspaces.get(workspace_id)
        if not workspace or workspace["tenant_id"] != tenant_id or workspace["owner_user_id"] != user_id:
            return None
        return deepcopy(workspace)

    def list_threads(self, tenant_id: str, user_id: str, workspace_id: str) -> list[dict[str, Any]]:
        if self.get_workspace(tenant_id, user_id, workspace_id) is None:
            raise PermissionError("analysis_workspace_not_owned")
        return [
            {**deepcopy(thread), "turns": deepcopy(self.turns.get(thread["thread_id"], []))}
            for thread in self.threads.values() if thread["workspace_id"] == workspace_id
        ]

    def create_thread(self, tenant_id: str, user_id: str, workspace_id: str, parent_thread_id: str | None, title: str, anchor: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self.get_workspace(tenant_id, user_id, workspace_id) is None:
                raise PermissionError("analysis_workspace_not_owned")
            parent = self.threads.get(parent_thread_id or "")
            if parent_thread_id and (not parent or parent["workspace_id"] != workspace_id or parent["tenant_id"] != tenant_id):
                raise PermissionError("analysis_parent_thread_not_owned")
            thread_id = f"thr_{uuid4().hex}"
            root_thread_id = parent["root_thread_id"] if parent else thread_id
            thread = {"thread_id": thread_id, "tenant_id": tenant_id, "workspace_id": workspace_id, "parent_thread_id": parent_thread_id, "root_thread_id": root_thread_id, "title": title or "分析分支", "anchor": deepcopy(anchor), "status": "active", "merged_into_thread_id": None, "created_at": _now(), "updated_at": _now()}
            self.threads[thread_id] = thread
            self.turns[thread_id] = []
            return deepcopy(thread)

    def append_turn(self, tenant_id: str, user_id: str, thread_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            thread = self._owned_thread(tenant_id, user_id, thread_id)
            if thread["status"] != "active":
                raise ValueError("analysis_thread_not_active")
            turn = {"turn_id": f"turn_{uuid4().hex}", "tenant_id": tenant_id, "thread_id": thread_id, "turn_no": len(self.turns[thread_id]) + 1, "actor_user_id": user_id, **deepcopy(payload), "created_at": _now()}
            self.turns[thread_id].append(turn)
            thread["updated_at"] = _now()
            return deepcopy(turn)

    def merge_threads(self, tenant_id: str, user_id: str, target_thread_id: str, source_thread_ids: list[str], question: str, answer: str, evidence_refs: list[dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            target = self._owned_thread(tenant_id, user_id, target_thread_id)
            sources = [self._owned_thread(tenant_id, user_id, item) for item in source_thread_ids]
            if any(source["workspace_id"] != target["workspace_id"] for source in sources):
                raise PermissionError("analysis_thread_merge_workspace_mismatch")
            turn = self.append_turn(tenant_id, user_id, target_thread_id, {"question": question, "answer": answer, "intent": {"primary_intent": "merge_conclusions"}, "execution_plan": {"source_thread_ids": source_thread_ids}, "artifact_refs": [], "evidence_refs": evidence_refs, "status": "completed"})
            for source in sources:
                source["status"] = "merged"
                source["merged_into_thread_id"] = target_thread_id
                source["updated_at"] = _now()
            return {"target_thread_id": target_thread_id, "source_thread_ids": source_thread_ids, "turn": turn}

    def _owned_thread(self, tenant_id: str, user_id: str, thread_id: str) -> dict[str, Any]:
        thread = self.threads.get(thread_id)
        if not thread or self.get_workspace(tenant_id, user_id, thread["workspace_id"]) is None:
            raise PermissionError("analysis_thread_not_owned")
        return thread


class MySQLAnalysisWorkspaceStore:
    def __init__(self, pool: MySQLConnectionPool) -> None:
        self.pool = pool

    def upsert_workspace(self, tenant_id: str, user_id: str, workspace_key: str, context: dict[str, Any]) -> dict[str, Any]:
        with self.pool.transaction() as connection, connection.cursor() as cursor:
            tenant_key, user_key = _resolve_identity(cursor, tenant_id, user_id)
            cursor.execute("SELECT workspace_id,owner_user_id FROM platform_analysis_workspaces WHERE tenant_id=%s AND workspace_key=%s FOR UPDATE", (tenant_key, workspace_key))
            row = cursor.fetchone()
            if row and str(row["owner_user_id"]) != user_key:
                raise PermissionError("analysis_workspace_not_owned")
            workspace_id = str(row["workspace_id"]) if row else str(uuid4())
            payload = _json(context)
            if row:
                cursor.execute("UPDATE platform_analysis_workspaces SET page_key=%s,artifact_ref=%s,context_snapshot=%s,status='active',updated_at=UTC_TIMESTAMP(6),lock_version=lock_version+1 WHERE workspace_id=%s", (context["page_key"], context.get("artifact_id", ""), payload, workspace_id))
            else:
                cursor.execute("INSERT INTO platform_analysis_workspaces(workspace_id,tenant_id,workspace_key,owner_user_id,page_key,artifact_ref,context_snapshot,status,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,'active',%s)", (workspace_id, tenant_key, workspace_key, user_key, context["page_key"], context.get("artifact_id", ""), payload, user_key))
                thread_id = str(uuid4())
                cursor.execute("INSERT INTO platform_analysis_threads(thread_id,tenant_id,workspace_id,parent_thread_id,root_thread_id,title,anchor,status,created_by) VALUES(%s,%s,%s,NULL,%s,'总体分析',JSON_OBJECT(),'active',%s)", (thread_id, tenant_key, workspace_id, thread_id, user_key))
        return self.get_workspace(tenant_id, user_id, workspace_id) or {}

    def get_workspace(self, tenant_id: str, user_id: str, workspace_id: str) -> dict[str, Any] | None:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            tenant_key, user_key = _resolve_identity(cursor, tenant_id, user_id)
            cursor.execute("SELECT workspace_id,workspace_key,page_key,artifact_ref,context_snapshot,status,created_at,updated_at FROM platform_analysis_workspaces WHERE workspace_id=%s AND tenant_id=%s AND owner_user_id=%s AND status<>'deleted'", (workspace_id, tenant_key, user_key))
            row = cursor.fetchone()
        return _workspace_row(row) if row else None

    def list_threads(self, tenant_id: str, user_id: str, workspace_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            tenant_key, user_key = _resolve_identity(cursor, tenant_id, user_id)
            _require_workspace(cursor, tenant_key, user_key, workspace_id)
            cursor.execute("SELECT thread_id,parent_thread_id,root_thread_id,title,anchor,status,merged_into_thread_id,created_at,updated_at FROM platform_analysis_threads WHERE tenant_id=%s AND workspace_id=%s ORDER BY created_at,thread_id", (tenant_key, workspace_id))
            threads = cursor.fetchall()
            cursor.execute("SELECT turn_id,thread_id,turn_no,question,answer,intent,execution_plan,artifact_refs,evidence_refs,status,created_at FROM platform_analysis_turns WHERE tenant_id=%s AND thread_id IN (SELECT thread_id FROM platform_analysis_threads WHERE workspace_id=%s) ORDER BY thread_id,turn_no", (tenant_key, workspace_id))
            turns = cursor.fetchall()
        by_thread: dict[str, list[dict[str, Any]]] = {}
        for row in turns:
            by_thread.setdefault(str(row["thread_id"]), []).append(_turn_row(row))
        return [{**_thread_row(row), "turns": by_thread.get(str(row["thread_id"]), [])} for row in threads]

    def create_thread(self, tenant_id: str, user_id: str, workspace_id: str, parent_thread_id: str | None, title: str, anchor: dict[str, Any]) -> dict[str, Any]:
        with self.pool.transaction() as connection, connection.cursor() as cursor:
            tenant_key, user_key = _resolve_identity(cursor, tenant_id, user_id)
            _require_workspace(cursor, tenant_key, user_key, workspace_id)
            root_id = None
            if parent_thread_id:
                cursor.execute("SELECT root_thread_id FROM platform_analysis_threads WHERE thread_id=%s AND tenant_id=%s AND workspace_id=%s", (parent_thread_id, tenant_key, workspace_id))
                parent = cursor.fetchone()
                if not parent:
                    raise PermissionError("analysis_parent_thread_not_owned")
                root_id = str(parent["root_thread_id"])
            thread_id = str(uuid4())
            root_id = root_id or thread_id
            cursor.execute("INSERT INTO platform_analysis_threads(thread_id,tenant_id,workspace_id,parent_thread_id,root_thread_id,title,anchor,status,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,'active',%s)", (thread_id, tenant_key, workspace_id, parent_thread_id, root_id, title or "分析分支", _json(anchor), user_key))
            cursor.execute("SELECT thread_id,workspace_id,parent_thread_id,root_thread_id,title,anchor,status,merged_into_thread_id,created_at,updated_at FROM platform_analysis_threads WHERE thread_id=%s", (thread_id,))
            created = cursor.fetchone()
        return {**_thread_row(created), "turns": []}

    def append_turn(self, tenant_id: str, user_id: str, thread_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.pool.transaction() as connection, connection.cursor() as cursor:
            tenant_key, user_key = _resolve_identity(cursor, tenant_id, user_id)
            cursor.execute("SELECT t.workspace_id,t.status,w.owner_user_id FROM platform_analysis_threads t JOIN platform_analysis_workspaces w ON w.workspace_id=t.workspace_id WHERE t.thread_id=%s AND t.tenant_id=%s FOR UPDATE", (thread_id, tenant_key))
            row = cursor.fetchone()
            if not row or str(row["owner_user_id"]) != user_key:
                raise PermissionError("analysis_thread_not_owned")
            if row["status"] != "active":
                raise ValueError("analysis_thread_not_active")
            cursor.execute("SELECT COALESCE(MAX(turn_no),0)+1 AS next_turn FROM platform_analysis_turns WHERE thread_id=%s", (thread_id,))
            turn_no = int(cursor.fetchone()["next_turn"])
            turn_id = str(uuid4())
            cursor.execute("INSERT INTO platform_analysis_turns(turn_id,tenant_id,thread_id,turn_no,actor_user_id,question,answer,intent,execution_plan,artifact_refs,evidence_refs,status,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (turn_id, tenant_key, thread_id, turn_no, user_key, payload["question"], payload["answer"], _json(payload["intent"]), _json(payload["execution_plan"]), _json(payload["artifact_refs"]), _json(payload["evidence_refs"]), payload["status"], user_key))
            cursor.execute("UPDATE platform_analysis_threads SET updated_at=UTC_TIMESTAMP(6),lock_version=lock_version+1 WHERE thread_id=%s", (thread_id,))
        return {"turn_id": turn_id, "thread_id": thread_id, "turn_no": turn_no, **payload}

    def merge_threads(self, tenant_id: str, user_id: str, target_thread_id: str, source_thread_ids: list[str], question: str, answer: str, evidence_refs: list[dict[str, Any]]) -> dict[str, Any]:
        with self.pool.transaction() as connection, connection.cursor() as cursor:
            tenant_key, user_key = _resolve_identity(cursor, tenant_id, user_id)
            placeholders = ",".join(["%s"] * (len(source_thread_ids) + 1))
            cursor.execute(f"SELECT t.thread_id,t.workspace_id,t.status,w.owner_user_id FROM platform_analysis_threads t JOIN platform_analysis_workspaces w ON w.workspace_id=t.workspace_id WHERE t.tenant_id=%s AND t.thread_id IN ({placeholders}) FOR UPDATE", (tenant_key, target_thread_id, *source_thread_ids))
            rows = cursor.fetchall()
            if len(rows) != len(source_thread_ids) + 1 or any(str(row["owner_user_id"]) != user_key for row in rows):
                raise PermissionError("analysis_thread_not_owned")
            if len({str(row["workspace_id"]) for row in rows}) != 1:
                raise PermissionError("analysis_thread_merge_workspace_mismatch")
            if any(row["status"] != "active" for row in rows):
                raise ValueError("analysis_thread_merge_state_invalid")
            cursor.execute("SELECT COALESCE(MAX(turn_no),0)+1 AS next_turn FROM platform_analysis_turns WHERE thread_id=%s", (target_thread_id,))
            turn_no = int(cursor.fetchone()["next_turn"])
            turn_id = str(uuid4())
            turn_payload = {"question": question, "answer": answer, "intent": {"primary_intent": "merge_conclusions"}, "execution_plan": {"source_thread_ids": source_thread_ids}, "artifact_refs": [], "evidence_refs": evidence_refs, "status": "completed"}
            cursor.execute("INSERT INTO platform_analysis_turns(turn_id,tenant_id,thread_id,turn_no,actor_user_id,question,answer,intent,execution_plan,artifact_refs,evidence_refs,status,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (turn_id, tenant_key, target_thread_id, turn_no, user_key, question, answer, _json(turn_payload["intent"]), _json(turn_payload["execution_plan"]), "[]", _json(evidence_refs), "completed", user_key))
            placeholders = ",".join(["%s"] * len(source_thread_ids))
            cursor.execute(f"UPDATE platform_analysis_threads SET status='merged',merged_into_thread_id=%s,updated_at=UTC_TIMESTAMP(6),lock_version=lock_version+1 WHERE tenant_id=%s AND thread_id IN ({placeholders})", (target_thread_id, tenant_key, *source_thread_ids))
            cursor.execute("UPDATE platform_analysis_threads SET updated_at=UTC_TIMESTAMP(6),lock_version=lock_version+1 WHERE thread_id=%s", (target_thread_id,))
        turn = {"turn_id": turn_id, "thread_id": target_thread_id, "turn_no": turn_no, **turn_payload}
        return {"target_thread_id": target_thread_id, "source_thread_ids": source_thread_ids, "turn": turn}


def provenance_dataset_snapshot(*sources: Any, schema_material: Any = None, content_material: Any = None) -> dict[str, Any]:
    """Normalize table/warehouse snapshots into the keys the evidence panel reads."""
    snapshot: dict[str, Any] = {}
    for source in sources:
        if isinstance(source, list):
            for item in source:
                _merge_snapshot_source(snapshot, item)
        else:
            _merge_snapshot_source(snapshot, source)
    if not _first_text(snapshot, "schema_fingerprint", "schema_hash", "schema_version"):
        fingerprint = _schema_fingerprint_from_material(schema_material)
        if fingerprint:
            snapshot["schema_fingerprint"] = fingerprint
    if not _first_text(snapshot, "content_hash", "artifact_sha256"):
        content = _content_hash_from_material(content_material, snapshot)
        if content:
            snapshot["content_hash"] = content
    version = _first_text(snapshot, "version", "asset_version", "snapshot_id", "content_hash", "artifact_sha256")
    schema = _first_text(snapshot, "schema_fingerprint", "schema_hash", "schema_version")
    content = _first_text(snapshot, "content_hash", "artifact_sha256")
    if version:
        snapshot["version"] = version
    if schema:
        snapshot["schema_fingerprint"] = schema
    if content:
        snapshot["content_hash"] = content
    return snapshot


def provenance_metric_versions(*sources: Any) -> list[dict[str, Any]]:
    """Accept metric_versions lists or metric_definition_versions maps."""
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for source in sources:
        for item in _metric_version_items(source):
            key = item["metric_id"]
            if key in seen or not _recorded_metric_version(item.get("version")):
                continue
            seen.add(key)
            result.append(item)
    return result


def manifest_has_display_provenance(manifest: dict[str, Any]) -> bool:
    snapshot = manifest.get("dataset_snapshot") if isinstance(manifest.get("dataset_snapshot"), dict) else {}
    has_version = any(str(snapshot.get(key) or "").strip() for key in ("version", "asset_version", "snapshot_id", "content_hash", "artifact_sha256"))
    has_schema = any(str(snapshot.get(key) or "").strip() for key in ("schema_fingerprint", "schemaFingerprint", "schema_hash", "schema_version"))
    return bool(has_version and has_schema)


def build_trusted_manifest(*, tenant_id: str, artifact_id: str, dataset_snapshot: dict[str, Any], metric_versions: list[dict[str, Any]], sql: str, result: Any, visualization: dict[str, Any], skill_versions: list[dict[str, Any]], model_version: str, authorization_snapshot: dict[str, Any], evidence_refs: list[dict[str, Any]], evaluation: dict[str, Any]) -> dict[str, Any]:
    snapshot = provenance_dataset_snapshot(dataset_snapshot)
    versions = provenance_metric_versions(metric_versions)
    manifest = {"manifest_version": 1, "tenant_id": tenant_id, "artifact_id": artifact_id, "dataset_snapshot": snapshot, "metric_versions": versions, "sql_hash": _hash(sql), "result_hash": _hash(result), "visualization_hash": _hash(visualization), "skill_versions": skill_versions, "model_version": model_version, "authorization_hash": _hash(authorization_snapshot), "evidence_refs": evidence_refs, "evaluation": evaluation, "created_at": _now()}
    return {**manifest, "manifest_hash": _hash(manifest)}


def verify_trusted_manifest(manifest: dict[str, Any]) -> bool:
    supplied_hash = str(manifest.get("manifest_hash") or "").strip().lower()
    if len(supplied_hash) != 64:
        return False
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_hash"}
    return hmac.compare_digest(supplied_hash, _hash(unsigned))


def safe_cache_key(*, tenant_id: str, question: str = "", authorization_snapshot: dict[str, Any], institution_ids: list[str], csv_snapshot: dict[str, Any], semantic_versions: list[dict[str, Any]], filters: dict[str, Any], time_grain: str, skill_versions: list[dict[str, Any]], model_version: str, code_version: str) -> str:
    return _hash({"tenant_id": tenant_id, "question": " ".join(question.casefold().split()), "authorization": authorization_snapshot, "institutions": sorted(institution_ids), "csv_snapshot": csv_snapshot, "semantic_versions": semantic_versions, "filters": filters, "time_grain": time_grain, "skill_versions": skill_versions, "model_version": model_version, "code_version": code_version})


def _resolve_identity(cursor: Any, tenant_id: str, user_id: str) -> tuple[str, str]:
    cursor.execute("SELECT tenant_id FROM platform_tenants WHERE tenant_code=%s AND status='active'", (tenant_id,))
    tenant = cursor.fetchone()
    cursor.execute("SELECT user_id FROM platform_user_profiles WHERE external_subject=%s AND status='active'", (user_id,))
    user = cursor.fetchone()
    if not tenant or not user:
        raise PermissionError("analysis_identity_not_provisioned")
    return str(tenant["tenant_id"]), str(user["user_id"])


def _require_workspace(cursor: Any, tenant_key: str, user_key: str, workspace_id: str) -> None:
    cursor.execute("SELECT 1 FROM platform_analysis_workspaces WHERE workspace_id=%s AND tenant_id=%s AND owner_user_id=%s AND status<>'deleted'", (workspace_id, tenant_key, user_key))
    if cursor.fetchone() is None:
        raise PermissionError("analysis_workspace_not_owned")


def _workspace_row(row: dict[str, Any]) -> dict[str, Any]:
    return _with_iso_times({**row, "workspace_id": str(row["workspace_id"]), "context_snapshot": _decoded(row.get("context_snapshot"), {})})


def _thread_row(row: dict[str, Any]) -> dict[str, Any]:
    return _with_iso_times({**row, "thread_id": str(row["thread_id"]), "parent_thread_id": str(row["parent_thread_id"]) if row.get("parent_thread_id") else None, "root_thread_id": str(row["root_thread_id"]), "anchor": _decoded(row.get("anchor"), {})})


def _turn_row(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["turn_id"] = str(row["turn_id"])
    result["thread_id"] = str(row["thread_id"])
    for key, default in (("intent", {}), ("execution_plan", {}), ("artifact_refs", []), ("evidence_refs", [])):
        result[key] = _decoded(row.get(key), default)
    return _with_iso_times(result)


def _with_iso_times(value: dict[str, Any]) -> dict[str, Any]:
    for key in ("created_at", "updated_at"):
        if isinstance(value.get(key), datetime):
            value[key] = value[key].replace(tzinfo=value[key].tzinfo or timezone.utc).isoformat()
    return value


def _bounded_object(value: Any) -> dict[str, Any]:
    result = value if isinstance(value, dict) else {}
    encoded = _json(result)
    if len(encoded.encode("utf-8")) > 256_000:
        raise ValueError("analysis_context_too_large")
    return deepcopy(result)


def _bounded_list(value: Any) -> list[dict[str, Any]]:
    result = [deepcopy(item) for item in value] if isinstance(value, list) and all(isinstance(item, dict) for item in value) else []
    if len(result) > 200 or len(_json(result).encode("utf-8")) > 256_000:
        raise ValueError("analysis_references_too_large")
    return result


def _required(value: Any, name: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{name}_required")
    return result


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decoded(value: Any, default: Any) -> Any:
    if isinstance(value, type(default)):
        return value
    try:
        return json.loads(value) if value else deepcopy(default)
    except (TypeError, json.JSONDecodeError):
        return deepcopy(default)


def _merge_snapshot_source(snapshot: dict[str, Any], source: Any) -> None:
    if not isinstance(source, dict):
        return
    nested = source.get("source_snapshot")
    if isinstance(nested, dict):
        _merge_snapshot_source(snapshot, nested)
    aliases = (
        ("id", ("id", "dataset_id", "datasetId", "table_id", "code")),
        ("table_id", ("table_id",)),
        ("dataset_id", ("dataset_id", "datasetId")),
        ("version", ("version", "asset_version", "assetVersion")),
        ("snapshot_id", ("snapshot_id", "snapshotId")),
        ("content_hash", ("content_hash", "contentHash", "artifact_sha256")),
        ("schema_fingerprint", ("schema_fingerprint", "schemaFingerprint", "schema_hash", "schema_version", "schemaVersion")),
        ("asset_version", ("asset_version", "assetVersion")),
        ("observed_at", ("observed_at", "generatedAt", "generated_at")),
        ("relative_path", ("relative_path", "relativePath")),
        ("source_key", ("source_key", "sourceKey")),
        ("immutable", ("immutable",)),
        ("artifact_sha256", ("artifact_sha256",)),
        ("page_data_id", ("page_data_id",)),
        ("relationship_group_id", ("relationship_group_id", "relationshipGroupId")),
        ("institution_scope", ("institution_scope",)),
        ("source_row_count", ("source_row_count",)),
    )
    for dest, keys in aliases:
        if snapshot.get(dest) not in (None, "", [], {}):
            continue
        for key in keys:
            value = source.get(key)
            if value not in (None, "", [], {}):
                snapshot[dest] = value
                break


def _metric_version_items(source: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(source, list):
        for item in source:
            if not isinstance(item, dict):
                continue
            metric_id = str(item.get("metric_id") or item.get("metricId") or item.get("metric_code") or item.get("metricCode") or "").strip()
            version = str(item.get("version") or item.get("semanticVersion") or item.get("version_id") or "").strip()
            if metric_id:
                items.append({"metric_id": metric_id, "version": version})
        return items
    if isinstance(source, dict) and source and all(not isinstance(value, (dict, list)) for value in source.values()):
        for key, value in source.items():
            metric_id = str(key).strip()
            if metric_id:
                items.append({"metric_id": metric_id, "version": str(value or "").strip()})
    return items


def _recorded_metric_version(value: Any) -> bool:
    version = str(value or "").strip().casefold()
    return bool(version) and version not in {"temporary", "table-field", "published", "pinned", "unbound"}


def _schema_fingerprint_from_material(material: Any) -> str:
    identity = _schema_identity(material)
    return _hash(identity) if identity not in (None, "", [], {}) else ""


def _schema_identity(material: Any) -> Any:
    parts = _collect_schema_parts(material)
    return parts or None


def _collect_schema_parts(material: Any) -> list[Any]:
    if material is None or material in ("", [], {}):
        return []
    if isinstance(material, str):
        text = material.strip()
        return [text] if text else []
    if isinstance(material, list):
        if material and all(isinstance(item, dict) for item in material):
            first = material[0]
            if any(key in first for key in ("fieldNameEn", "fieldNameCn", "field_name_en")):
                return [[{"name": str(item.get("fieldNameEn") or item.get("code") or item.get("name") or ""), "type": str(item.get("type") or "")} for item in material]]
            if any("kind" in item or "tableNameEn" in item or "code" in item and "id" in item for item in material[:3]):
                parts: list[Any] = []
                for item in material:
                    parts.extend(_collect_schema_parts(item))
                return parts
            return [sorted(str(key) for key in first if not str(key).startswith("_") and str(key) not in {"fieldLabels", "field_labels", "raw"})]
        parts = []
        for item in material:
            parts.extend(_collect_schema_parts(item))
        return parts
    if not isinstance(material, dict):
        return []
    parts = []
    if "schema_mapping" in material:
        parts.extend(_collect_schema_parts(material.get("schema_mapping")))
    labels = material.get("field_labels") or material.get("fieldLabels")
    if isinstance(labels, dict) and labels:
        parts.append(sorted(str(key) for key in labels))
    if material.get("fields"):
        parts.extend(_collect_schema_parts(material.get("fields")))
    metrics = material.get("metrics") if isinstance(material.get("metrics"), list) else material.get("metric")
    dimensions = material.get("dimensions") if isinstance(material.get("dimensions"), list) else material.get("dimension")
    if metrics or dimensions:
        parts.append({"metrics": metrics or [], "dimensions": dimensions or []})
    elif not parts and all(not isinstance(value, (dict, list)) for value in material.values()):
        parts.append(sorted(str(key) for key in material))
    return parts


def _content_hash_from_material(material: Any, snapshot: dict[str, Any]) -> str:
    rows = material if isinstance(material, list) else []
    bounded: list[dict[str, Any]] = []
    for item in rows[:200]:
        if not isinstance(item, dict):
            continue
        bounded.append({str(key): item[key] for key in item if not str(key).startswith("_") and str(key) not in {"fieldLabels", "field_labels"}})
    identity = {
        "id": str(snapshot.get("id") or snapshot.get("table_id") or snapshot.get("dataset_id") or "").strip(),
        "source_key": str(snapshot.get("source_key") or "").strip(),
        "relative_path": str(snapshot.get("relative_path") or "").strip(),
        "rows": bounded,
    }
    if not identity["id"] and not bounded:
        return ""
    return _hash(identity)


def _first_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _hash(value: Any) -> str:
    normalized = value if isinstance(value, str) else _json(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
