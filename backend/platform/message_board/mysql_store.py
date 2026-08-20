from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.mysql import MySQLConnectionPool

from .store import MessageBoardRevisionConflict


class MySQLMessageBoardStore:
    def __init__(self, pool: MySQLConnectionPool) -> None:
        self.pool = pool

    def create(self, entry: dict[str, Any]) -> dict[str, Any]:
        with self.pool.transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, entry["tenant_id"])
            author_key = PostgreSQLIdentityResolver.user_id(connection, entry["author_user_id"])
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT IGNORE INTO platform_message_board_entries(
                        message_key, tenant_id, author_user_id, author_name,
                        page_key, page_title, page_url, content, quote_context,
                        attachment_ids, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        entry["message_id"], tenant_key, author_key, entry["author_name"],
                        entry["page_key"], entry["page_title"], entry["page_url"], entry["content"],
                        _json(entry["quote_context"]), _json(entry["attachment_ids"]), author_key,
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
        with self.pool.transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            user_key = PostgreSQLIdentityResolver.user_id(connection, user_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_message_board_entries
                    SET content=%s, quote_context=%s, attachment_ids=%s,
                        updated_at=UTC_TIMESTAMP(6), lock_version=lock_version+1
                    WHERE message_key=%s AND tenant_id=%s AND author_user_id=%s
                      AND status <> 'completed' AND lock_version=%s
                    """,
                    (
                        patch["content"], _json(patch["quote_context"]), _json(patch["attachment_ids"]),
                        message_id, tenant_key, user_key, expected_lock_version,
                    ),
                )
                changed = cursor.rowcount
        if changed != 1:
            current = self._get(message_id)
            if current["tenant_id"] != tenant_id:
                raise KeyError("message_board_entry_not_found")
            if current["author_user_id"] != user_id:
                raise PermissionError("message_board_entry_owner_required")
            if current.get("status") == "completed":
                raise PermissionError("message_board_entry_completed")
            raise MessageBoardRevisionConflict("message_board_revision_conflict")
        return self._get(message_id)

    def archive_owned(self, tenant_id: str, user_id: str, message_id: str, expected_lock_version: int) -> dict[str, Any]:
        with self.pool.transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            user_key = PostgreSQLIdentityResolver.user_id(connection, user_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_message_board_entries
                    SET status='completed', archived_at=UTC_TIMESTAMP(6),
                        updated_at=UTC_TIMESTAMP(6), lock_version=lock_version+1
                    WHERE message_key=%s AND tenant_id=%s AND author_user_id=%s AND lock_version=%s
                    """,
                    (message_id, tenant_key, user_key, expected_lock_version),
                )
                changed = cursor.rowcount
        if changed != 1:
            current = self._get(message_id)
            if current["tenant_id"] != tenant_id:
                raise KeyError("message_board_entry_not_found")
            if current["author_user_id"] != user_id:
                raise PermissionError("message_board_entry_owner_required")
            raise MessageBoardRevisionConflict("message_board_revision_conflict")
        return self._get(message_id)

    def delete_owned(self, tenant_id: str, user_id: str, message_id: str, expected_lock_version: int) -> dict[str, Any]:
        current = self._get(message_id)
        with self.pool.transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            user_key = PostgreSQLIdentityResolver.user_id(connection, user_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM platform_message_board_entries
                    WHERE message_key=%s AND tenant_id=%s AND author_user_id=%s AND lock_version=%s
                    """,
                    (message_id, tenant_key, user_key, expected_lock_version),
                )
                changed = cursor.rowcount
        if changed != 1:
            latest = self._get(message_id)
            if latest["tenant_id"] != tenant_id:
                raise KeyError("message_board_entry_not_found")
            if latest["author_user_id"] != user_id:
                raise PermissionError("message_board_entry_owner_required")
            raise MessageBoardRevisionConflict("message_board_revision_conflict")
        return current

    def set_status(self, message_id: str, status: str, expected_lock_version: int) -> dict[str, Any]:
        with self.pool.transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE platform_message_board_entries
                SET status=%s,
                    archived_at=CASE WHEN %s='completed' THEN UTC_TIMESTAMP(6) ELSE NULL END,
                    updated_at=UTC_TIMESTAMP(6), lock_version=lock_version+1
                WHERE message_key=%s AND lock_version=%s
                """,
                (status, status, message_id, expected_lock_version),
            )
            changed = cursor.rowcount
        if changed != 1:
            self._get(message_id)
            raise MessageBoardRevisionConflict("message_board_revision_conflict")
        return self._get(message_id)

    def list_owned(self, tenant_id: str, user_id: str, page_key: str = "") -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            user_key = PostgreSQLIdentityResolver.user_id(connection, user_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    self._select() + """
                    WHERE e.tenant_id=%s AND e.author_user_id=%s AND (%s='' OR e.page_key=%s)
                    ORDER BY e.created_at DESC, e.message_key DESC
                    """,
                    (tenant_key, user_key, page_key, page_key),
                )
                rows = list(cursor.fetchall())
        return [_row(row) for row in rows]

    def list_all(self, *, tenant_id: str = "", query: str = "", offset: int = 0, limit: int = 50) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        params: list[Any] = []
        if str(tenant_id or "").strip():
            clauses.append("tenant.tenant_code=%s")
            params.append(str(tenant_id).strip())
        if query.strip():
            clauses.append("LOWER(CONCAT(e.author_name, ' ', author.external_subject, ' ', e.content, ' ', e.page_title, ' ', tenant.tenant_code)) LIKE %s")
            params.append(f"%{query.strip().lower()}%")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS total FROM platform_message_board_entries e "
                "JOIN platform_tenants tenant ON tenant.tenant_id=e.tenant_id "
                "JOIN platform_user_profiles author ON author.user_id=e.author_user_id " + where,
                params,
            )
            total = int(_value(cursor.fetchone(), "total", 0) or 0)
            cursor.execute(
                self._select() + where + " ORDER BY e.created_at DESC, e.message_key DESC LIMIT %s OFFSET %s",
                (*params, limit, offset),
            )
            rows = list(cursor.fetchall())
        return [_row(row) for row in rows], total

    def _get(self, message_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(self._select() + " WHERE e.message_key=%s", (message_id,))
            row = cursor.fetchone()
        if not row:
            raise KeyError("message_board_entry_not_found")
        return _row(row)

    @staticmethod
    def _select() -> str:
        return """
            SELECT e.message_key, tenant.tenant_code, author.external_subject,
                   COALESCE(NULLIF(TRIM(author.display_name), ''), e.author_name) AS author_name,
                   e.page_key, e.page_title, e.page_url, e.content,
                   e.quote_context, e.attachment_ids, e.created_at, e.updated_at, e.lock_version,
                   e.status, e.archived_at
            FROM platform_message_board_entries e
            JOIN platform_tenants tenant ON tenant.tenant_id=e.tenant_id
            JOIN platform_user_profiles author ON author.user_id=e.author_user_id
        """

    def close(self) -> None:
        return


def _row(row: Any) -> dict[str, Any]:
    return {
        "message_id": str(_value(row, "message_key", 0)),
        "tenant_id": str(_value(row, "tenant_code", 1)),
        "author_user_id": str(_value(row, "external_subject", 2)),
        "author_name": str(_value(row, "author_name", 3)),
        "page_key": str(_value(row, "page_key", 4)),
        "page_title": str(_value(row, "page_title", 5)),
        "page_url": str(_value(row, "page_url", 6)),
        "content": str(_value(row, "content", 7)),
        "quote_context": _json_value(_value(row, "quote_context", 8), {}),
        "attachment_ids": _json_value(_value(row, "attachment_ids", 9), []),
        "created_at": _iso(_value(row, "created_at", 10)),
        "updated_at": _iso(_value(row, "updated_at", 11)),
        "lock_version": int(_value(row, "lock_version", 12) or 0),
        "status": str(_value(row, "status", 13) or "new"),
        "archived_at": _iso(_value(row, "archived_at", 14)) or None,
    }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return default


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat()
    return str(value or "")


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[index]
    except (TypeError, IndexError):
        return None
