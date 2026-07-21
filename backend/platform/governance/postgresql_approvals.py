from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.postgresql import PostgreSQLConnectionPool

from .approvals import _bounded_ttl, _new_request, _validate_consumption, _validate_review


class PostgreSQLCapabilityApprovalStore:
    """Transactional, one-time approval tickets for production Skill/MCP calls."""

    def __init__(self, pool: PostgreSQLConnectionPool, *, owns_pool: bool = False) -> None:
        self.pool = pool
        self.owns_pool = owns_pool

    def close(self) -> None:
        if self.owns_pool:
            self.pool.close()

    def request(
        self,
        tenant_id: str,
        subject_type: str,
        subject_id: str,
        action: str,
        input_hash: str,
        requested_by: str,
        reason: str = "",
    ) -> dict[str, Any]:
        item = _new_request(tenant_id, subject_type, subject_id, action, input_hash, requested_by, reason)
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            user_key = PostgreSQLIdentityResolver.user_id(connection, requested_by)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_capability_approvals(
                        tenant_id, approval_key, subject_type, subject_id, action,
                        input_hash, reason, requested_by, requested_at, status, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::timestamptz, 'pending', %s)
                    """,
                    (
                        tenant_key, item["approval_id"], subject_type, subject_id, action,
                        input_hash.lower(), item["reason"], user_key, item["requested_at"], user_key,
                    ),
                )
        return item

    def review(
        self,
        tenant_id: str,
        approval_id: str,
        reviewer_user_id: str,
        decision: str,
        *,
        ttl_seconds: int = 900,
        comments: str = "",
    ) -> dict[str, Any]:
        with self._transaction() as connection:
            item = self._get(connection, tenant_id, approval_id, for_update=True)
            _validate_review(item, reviewer_user_id, decision)
            reviewer_key = PostgreSQLIdentityResolver.user_id(connection, reviewer_user_id)
            status = "approved" if decision == "approved" else "rejected"
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=_bounded_ttl(ttl_seconds))
                if status == "approved" else None
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_capability_approvals
                    SET status = %s, reviewed_by = %s, reviewed_at = now(), expires_at = %s,
                        review_comment = %s, updated_at = now(), lock_version = lock_version + 1
                    WHERE approval_key = %s AND status = 'pending'
                    """,
                    (status, reviewer_key, expires_at, str(comments or "")[:2000], approval_id),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("capability_approval_concurrent_review")
        return self.get(tenant_id, approval_id)

    def consume(
        self,
        approval_id: str,
        *,
        tenant_id: str,
        requested_by: str,
        subject_type: str,
        subject_id: str,
        action: str,
        input_hash: str,
    ) -> dict[str, Any]:
        with self._transaction() as connection:
            try:
                item = self._get(connection, tenant_id, approval_id, for_update=True)
            except KeyError as exc:
                raise PermissionError("capability_approval_invalid") from exc
            _validate_consumption(item, tenant_id, requested_by, subject_type, subject_id, action, input_hash)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_capability_approvals
                    SET status = 'consumed', consumed_at = now(), updated_at = now(),
                        lock_version = lock_version + 1
                    WHERE approval_key = %s AND status = 'approved' AND expires_at > now()
                    """,
                    (approval_id,),
                )
                if cursor.rowcount != 1:
                    raise PermissionError("capability_approval_already_consumed")
        return self.get(tenant_id, approval_id)

    def get(self, tenant_id: str, approval_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            return self._get(connection, tenant_id, approval_id)

    def list(self, tenant_id: str, status: str | None = None) -> list[dict[str, Any]]:
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_capability_approvals
                    SET status = 'expired', updated_at = now(), lock_version = lock_version + 1
                    WHERE tenant_id = %s AND status = 'approved' AND expires_at <= now()
                    """,
                    (tenant_key,),
                )
                params: list[Any] = [tenant_key]
                where = "WHERE a.tenant_id = %s"
                if status:
                    where += " AND a.status = %s"
                    params.append(status)
                cursor.execute(self._select_sql(where) + " ORDER BY a.requested_at DESC LIMIT 200", tuple(params))
                rows = cursor.fetchall()
        return [self._from_row(row) for row in rows]

    def _get(self, connection: Any, tenant_id: str, approval_id: str, *, for_update: bool = False) -> dict[str, Any]:
        tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
        suffix = " FOR UPDATE OF a" if for_update else ""
        with connection.cursor() as cursor:
            cursor.execute(
                self._select_sql("WHERE a.tenant_id = %s AND a.approval_key = %s") + suffix,
                (tenant_key, approval_id),
            )
            row = cursor.fetchone()
        if not row:
            raise KeyError("capability_approval_not_found")
        return self._from_row(row)

    @staticmethod
    def _select_sql(where: str) -> str:
        return f"""
            SELECT a.approval_key, t.tenant_code, a.subject_type, a.subject_id,
                   a.action, a.input_hash, a.reason, requester.external_subject AS requested_by,
                   a.requested_at, a.status, reviewer.external_subject AS reviewed_by,
                   a.reviewed_at, a.expires_at, a.consumed_at, a.review_comment
            FROM platform_capability_approvals a
            JOIN platform_tenants t ON t.tenant_id = a.tenant_id
            JOIN platform_user_profiles requester ON requester.user_id = a.requested_by
            LEFT JOIN platform_user_profiles reviewer ON reviewer.user_id = a.reviewed_by
            {where}
        """

    @staticmethod
    def _from_row(row: Any) -> dict[str, Any]:
        keys = (
            "approval_id", "tenant_id", "subject_type", "subject_id", "action",
            "input_hash", "reason", "requested_by", "requested_at", "status",
            "reviewed_by", "reviewed_at", "expires_at", "consumed_at", "review_comment",
        )
        db_keys = (
            "approval_key", "tenant_code", "subject_type", "subject_id", "action",
            "input_hash", "reason", "requested_by", "requested_at", "status",
            "reviewed_by", "reviewed_at", "expires_at", "consumed_at", "review_comment",
        )
        result: dict[str, Any] = {}
        for index, (key, db_key) in enumerate(zip(keys, db_keys)):
            value = _value(row, db_key, index)
            result[key] = value.isoformat() if isinstance(value, datetime) else value
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


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]
