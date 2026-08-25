from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from backend.platform.storage import connect_sqlite


class MessageBoardRevisionConflict(RuntimeError):
    pass


class InMemoryMessageBoardStore:
    def __init__(self) -> None:
        self._entries: dict[str, dict[str, Any]] = {}
        self._guard = RLock()

    def create(self, entry: dict[str, Any]) -> dict[str, Any]:
        with self._guard:
            current = self._entries.get(entry["message_id"])
            if current:
                if current["tenant_id"] != entry["tenant_id"] or current["author_user_id"] != entry["author_user_id"]:
                    raise PermissionError("message_board_entry_owner_mismatch")
                return dict(current)
            now = _utcnow()
            stored = {
                **entry,
                "status": entry.get("status") or "new",
                "append_content": str(entry.get("append_content") or ""),
                "archived_at": None,
                "created_at": now,
                "updated_at": now,
                "lock_version": 0,
            }
            self._entries[entry["message_id"]] = stored
            return dict(stored)

    def update(
        self,
        tenant_id: str,
        user_id: str,
        message_id: str,
        patch: dict[str, Any],
        expected_lock_version: int,
    ) -> dict[str, Any]:
        with self._guard:
            current = self._entries.get(message_id)
            if not current or current["tenant_id"] != tenant_id:
                raise KeyError("message_board_entry_not_found")
            if current["author_user_id"] != user_id:
                raise PermissionError("message_board_entry_owner_required")
            if current.get("status") == "completed":
                raise PermissionError("message_board_entry_completed")
            if int(current["lock_version"]) != expected_lock_version:
                raise MessageBoardRevisionConflict("message_board_revision_conflict")
            current.update(patch)
            current["lock_version"] = expected_lock_version + 1
            current["updated_at"] = _utcnow()
            return dict(current)

    def archive_owned(self, tenant_id: str, user_id: str, message_id: str, expected_lock_version: int) -> dict[str, Any]:
        with self._guard:
            current = self._entries.get(message_id)
            if not current or current["tenant_id"] != tenant_id:
                raise KeyError("message_board_entry_not_found")
            if current["author_user_id"] != user_id:
                raise PermissionError("message_board_entry_owner_required")
            if int(current["lock_version"]) != expected_lock_version:
                raise MessageBoardRevisionConflict("message_board_revision_conflict")
            current["status"] = "completed"
            current["archived_at"] = _utcnow()
            current["lock_version"] = expected_lock_version + 1
            current["updated_at"] = current["archived_at"]
            return dict(current)

    def delete_owned(self, tenant_id: str, user_id: str, message_id: str, expected_lock_version: int) -> dict[str, Any]:
        with self._guard:
            current = self._entries.get(message_id)
            if not current or current["tenant_id"] != tenant_id:
                raise KeyError("message_board_entry_not_found")
            if current["author_user_id"] != user_id:
                raise PermissionError("message_board_entry_owner_required")
            if int(current["lock_version"]) != expected_lock_version:
                raise MessageBoardRevisionConflict("message_board_revision_conflict")
            removed = dict(current)
            del self._entries[message_id]
            return removed

    def set_status(self, message_id: str, status: str, expected_lock_version: int) -> dict[str, Any]:
        with self._guard:
            current = self._entries.get(message_id)
            if not current:
                raise KeyError("message_board_entry_not_found")
            if int(current["lock_version"]) != expected_lock_version:
                raise MessageBoardRevisionConflict("message_board_revision_conflict")
            current["status"] = status
            current["archived_at"] = _utcnow() if status == "completed" else None
            current["lock_version"] = expected_lock_version + 1
            current["updated_at"] = _utcnow()
            return dict(current)

    def set_append_content(self, message_id: str, append_content: str, expected_lock_version: int) -> dict[str, Any]:
        with self._guard:
            current = self._entries.get(message_id)
            if not current:
                raise KeyError("message_board_entry_not_found")
            if int(current["lock_version"]) != expected_lock_version:
                raise MessageBoardRevisionConflict("message_board_revision_conflict")
            current["append_content"] = append_content
            current["lock_version"] = expected_lock_version + 1
            current["updated_at"] = _utcnow()
            return dict(current)

    def list_owned(self, tenant_id: str, user_id: str, page_key: str = "") -> list[dict[str, Any]]:
        with self._guard:
            rows = [
                dict(entry)
                for entry in self._entries.values()
                if entry["tenant_id"] == tenant_id
                and entry["author_user_id"] == user_id
                and (not page_key or entry["page_key"] == page_key)
            ]
        return sorted(rows, key=lambda item: (item["created_at"], item["message_id"]), reverse=True)

    def list_all(self, *, tenant_id: str = "", query: str = "", offset: int = 0, limit: int = 50, status: str = "", sort: str = "") -> tuple[list[dict[str, Any]], int]:
        needle = query.strip().lower()
        scoped = str(tenant_id or "").strip()
        wanted_status = str(status or "").strip()
        with self._guard:
            rows = [
                dict(entry)
                for entry in self._entries.values()
                if (not scoped or entry.get("tenant_id") == scoped)
                and (not wanted_status or entry.get("status") == wanted_status)
            ]
        if needle:
            rows = [
                entry for entry in rows
                if needle in " ".join(
                    str(entry.get(key) or "")
                    for key in ("author_name", "author_user_id", "content", "page_title", "tenant_id")
                ).lower()
            ]
        rows.sort(key=lambda item: (item["created_at"], item["message_id"]), reverse=str(sort or "").strip().lower() != "asc")
        return rows[offset : offset + limit], len(rows)

    def close(self) -> None:
        return


class SQLiteMessageBoardStore:
    def __init__(self, db_path: str | Path, *, initialize: bool = True) -> None:
        self._conn = connect_sqlite(db_path)
        self._conn.row_factory = sqlite3.Row
        if initialize:
            self.init_schema()

    def init_schema(self) -> None:
        migration = Path(__file__).resolve().parents[1] / "database" / "sql" / "0029_message_board.sql"
        self._conn.executescript(migration.read_text(encoding="utf-8"))
        columns = {str(row[1]) for row in self._conn.execute("PRAGMA table_info(platform_message_board_entries)")}
        if "status" not in columns:
            self._conn.execute("ALTER TABLE platform_message_board_entries ADD COLUMN status TEXT NOT NULL DEFAULT 'new'")
        if "archived_at" not in columns:
            self._conn.execute("ALTER TABLE platform_message_board_entries ADD COLUMN archived_at TEXT")
        if "append_content" not in columns:
            self._conn.execute("ALTER TABLE platform_message_board_entries ADD COLUMN append_content TEXT NOT NULL DEFAULT ''")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_platform_message_board_status "
            "ON platform_message_board_entries(status, updated_at DESC, message_id)"
        )
        self._conn.commit()

    def create(self, entry: dict[str, Any]) -> dict[str, Any]:
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO platform_message_board_entries(
                    message_id, tenant_id, author_user_id, author_name,
                    page_key, page_title, page_url, content, quote_context,
                    attachment_ids, status, archived_at, append_content, created_at, updated_at, lock_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, 0)
                """,
                (
                    entry["message_id"], entry["tenant_id"], entry["author_user_id"], entry["author_name"],
                    entry["page_key"], entry["page_title"], entry["page_url"], entry["content"],
                    _json(entry["quote_context"]), _json(entry["attachment_ids"]), entry.get("status") or "new",
                    str(entry.get("append_content") or ""), now, now,
                ),
            )
        saved = self._get(entry["message_id"])
        if saved["tenant_id"] != entry["tenant_id"] or saved["author_user_id"] != entry["author_user_id"]:
            raise PermissionError("message_board_entry_owner_mismatch")
        return saved

    def update(
        self,
        tenant_id: str,
        user_id: str,
        message_id: str,
        patch: dict[str, Any],
        expected_lock_version: int,
    ) -> dict[str, Any]:
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE platform_message_board_entries
                SET content = ?, quote_context = ?, attachment_ids = ?,
                    updated_at = ?, lock_version = lock_version + 1
                WHERE message_id = ? AND tenant_id = ? AND author_user_id = ?
                  AND status <> 'completed' AND lock_version = ?
                """,
                (
                    patch["content"], _json(patch["quote_context"]), _json(patch["attachment_ids"]),
                    _utcnow(), message_id, tenant_id, user_id, expected_lock_version,
                ),
            )
        if cursor.rowcount != 1:
            current = self._conn.execute(
                "SELECT tenant_id, author_user_id, status, lock_version FROM platform_message_board_entries WHERE message_id = ?",
                (message_id,),
            ).fetchone()
            if not current or current["tenant_id"] != tenant_id:
                raise KeyError("message_board_entry_not_found")
            if current["author_user_id"] != user_id:
                raise PermissionError("message_board_entry_owner_required")
            if current["status"] == "completed":
                raise PermissionError("message_board_entry_completed")
            raise MessageBoardRevisionConflict("message_board_revision_conflict")
        return self._get(message_id)

    def archive_owned(self, tenant_id: str, user_id: str, message_id: str, expected_lock_version: int) -> dict[str, Any]:
        now = _utcnow()
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE platform_message_board_entries
                SET status = 'completed', archived_at = ?, updated_at = ?, lock_version = lock_version + 1
                WHERE message_id = ? AND tenant_id = ? AND author_user_id = ? AND lock_version = ?
                """,
                (now, now, message_id, tenant_id, user_id, expected_lock_version),
            )
        if cursor.rowcount != 1:
            self._raise_write_failure(tenant_id, user_id, message_id)
        return self._get(message_id)

    def delete_owned(self, tenant_id: str, user_id: str, message_id: str, expected_lock_version: int) -> dict[str, Any]:
        current = self._get(message_id)
        with self._conn:
            cursor = self._conn.execute(
                """
                DELETE FROM platform_message_board_entries
                WHERE message_id = ? AND tenant_id = ? AND author_user_id = ? AND lock_version = ?
                """,
                (message_id, tenant_id, user_id, expected_lock_version),
            )
        if cursor.rowcount != 1:
            self._raise_write_failure(tenant_id, user_id, message_id)
        return current

    def set_status(self, message_id: str, status: str, expected_lock_version: int) -> dict[str, Any]:
        now = _utcnow()
        archived_at = now if status == "completed" else None
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE platform_message_board_entries
                SET status = ?, archived_at = ?, updated_at = ?, lock_version = lock_version + 1
                WHERE message_id = ? AND lock_version = ?
                """,
                (status, archived_at, now, message_id, expected_lock_version),
            )
        if cursor.rowcount != 1:
            if not self._conn.execute("SELECT 1 FROM platform_message_board_entries WHERE message_id = ?", (message_id,)).fetchone():
                raise KeyError("message_board_entry_not_found")
            raise MessageBoardRevisionConflict("message_board_revision_conflict")
        return self._get(message_id)

    def set_append_content(self, message_id: str, append_content: str, expected_lock_version: int) -> dict[str, Any]:
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE platform_message_board_entries
                SET append_content = ?, updated_at = ?, lock_version = lock_version + 1
                WHERE message_id = ? AND lock_version = ?
                """,
                (append_content, _utcnow(), message_id, expected_lock_version),
            )
        if cursor.rowcount != 1:
            if not self._conn.execute("SELECT 1 FROM platform_message_board_entries WHERE message_id = ?", (message_id,)).fetchone():
                raise KeyError("message_board_entry_not_found")
            raise MessageBoardRevisionConflict("message_board_revision_conflict")
        return self._get(message_id)

    def _raise_write_failure(self, tenant_id: str, user_id: str, message_id: str) -> None:
        current = self._conn.execute(
            "SELECT tenant_id, author_user_id FROM platform_message_board_entries WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        if not current or current["tenant_id"] != tenant_id:
            raise KeyError("message_board_entry_not_found")
        if current["author_user_id"] != user_id:
            raise PermissionError("message_board_entry_owner_required")
        raise MessageBoardRevisionConflict("message_board_revision_conflict")

    def list_owned(self, tenant_id: str, user_id: str, page_key: str = "") -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT * FROM platform_message_board_entries
            WHERE tenant_id = ? AND author_user_id = ? AND (? = '' OR page_key = ?)
            ORDER BY created_at DESC, message_id DESC
            """,
            (tenant_id, user_id, page_key, page_key),
        ).fetchall()
        return [_row(row) for row in rows]

    def list_all(self, *, tenant_id: str = "", query: str = "", offset: int = 0, limit: int = 50, status: str = "", sort: str = "") -> tuple[list[dict[str, Any]], int]:
        pattern = f"%{query.strip().lower()}%"
        clauses: list[str] = []
        params: list[Any] = []
        if str(tenant_id or "").strip():
            clauses.append("tenant_id = ?")
            params.append(str(tenant_id).strip())
        if str(status or "").strip():
            clauses.append("status = ?")
            params.append(str(status).strip())
        if query.strip():
            clauses.append("lower(author_name || ' ' || author_user_id || ' ' || content || ' ' || page_title || ' ' || tenant_id) LIKE ?")
            params.append(pattern)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        direction = "ASC" if str(sort or "").strip().lower() == "asc" else "DESC"
        total = int(self._conn.execute(f"SELECT COUNT(*) FROM platform_message_board_entries {where}", params).fetchone()[0])
        rows = self._conn.execute(
            f"SELECT * FROM platform_message_board_entries {where} ORDER BY created_at {direction}, message_id {direction} LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [_row(row) for row in rows], total

    def _get(self, message_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM platform_message_board_entries WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        if not row:
            raise KeyError("message_board_entry_not_found")
        return _row(row)

    def close(self) -> None:
        self._conn.close()


def _row(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["quote_context"] = json.loads(value.get("quote_context") or "{}")
    value["attachment_ids"] = json.loads(value.get("attachment_ids") or "[]")
    value["append_content"] = str(value.get("append_content") or "")
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
