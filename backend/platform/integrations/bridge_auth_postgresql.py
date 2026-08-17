from __future__ import annotations

import sqlite3
from typing import Any

from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.postgresql import PostgreSQLConnectionPool
from backend.platform.security import AuthenticationError

from .bridge_auth import (
    DEFAULT_ENROLLMENT_TTL_SECONDS,
    _binding_output,
    _channel,
    _enrollment_window,
    _hash,
    _new_binding,
    _new_enrollment,
    _now,
    _preview,
    _required,
    _start_result,
    _user_code_hash,
    _validate_enrollment_available,
    _validate_poll,
    _verifier_hash,
)


class PostgreSQLBridgeAuthStore:
    def __init__(self, pool: PostgreSQLConnectionPool, *, owns_pool: bool = False) -> None:
        self.pool = pool
        self.owns_pool = owns_pool

    def close(self) -> None:
        if self.owns_pool:
            self.pool.close()

    def start_enrollment(self, channel: str, device_name: str, verifier_hash: str, **kwargs: Any) -> dict[str, Any]:
        current, expires_at = _enrollment_window(kwargs.get("now"), kwargs.get("ttl_seconds", DEFAULT_ENROLLMENT_TTL_SECONDS))
        normalized_channel = _channel(channel)
        normalized_verifier_hash = _verifier_hash(verifier_hash)
        for _ in range(5):
            enrollment = _new_enrollment(normalized_channel, device_name, normalized_verifier_hash, current, expires_at)
            try:
                with self.pool.connection() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            INSERT INTO platform_bridge_enrollments(
                                enrollment_key, device_code_hash, user_code_hash, channel,
                                device_name, verifier_hash, status, expires_at_epoch, created_at_epoch
                            ) VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s, %s)
                            """,
                            (
                                enrollment["enrollment_id"], enrollment["device_code_hash"], enrollment["user_code_hash"],
                                enrollment["channel"], enrollment["device_name"], enrollment["verifier_hash"],
                                enrollment["expires_at"], enrollment["created_at"],
                            ),
                        )
                    connection.commit()
                return _start_result(enrollment)
            except Exception as exc:
                if _is_unique_violation(exc):
                    continue
                raise
        raise RuntimeError("bridge_enrollment_code_generation_failed")

    def enrollment_preview(self, user_code: str, *, now: int | None = None) -> dict[str, Any]:
        with self.pool.connection() as connection:
            record = self._enrollment_by(connection, "e.user_code_hash = %s", (_user_code_hash(user_code),))
        _validate_enrollment_available(record, _now(now))
        return _preview(record)

    def approve_enrollment(self, user_code: str, tenant_id: str, user_id: str, approved_by: str, *, now: int | None = None) -> dict[str, Any]:
        current = _now(now)
        with self.pool.connection() as connection:
            try:
                record = self._enrollment_by(
                    connection,
                    "e.user_code_hash = %s",
                    (_user_code_hash(user_code),),
                    for_update=True,
                )
                _validate_enrollment_available(record, current)
                if record["status"] == "approved":
                    if record["tenant_id"] != tenant_id or record["user_id"] != user_id:
                        raise PermissionError("bridge_enrollment_already_approved")
                    connection.commit()
                    return _preview(record)
                tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, _required(tenant_id, "bridge_enrollment_tenant_required"))
                user_key = PostgreSQLIdentityResolver.user_id(connection, _required(user_id, "bridge_enrollment_user_required"))
                approver_key = PostgreSQLIdentityResolver.user_id(connection, _required(approved_by, "bridge_enrollment_approver_required"))
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE platform_bridge_enrollments
                        SET status = 'approved', tenant_id = %s, user_id = %s,
                            approved_by = %s, approved_at_epoch = %s, updated_at = now()
                        WHERE enrollment_id = %s AND status = 'pending' AND consumed_at_epoch IS NULL
                        """,
                        (tenant_key, user_key, approver_key, current, record["enrollment_uuid"]),
                    )
                connection.commit()
                return {
                    "channel": record["channel"],
                    "device_name": record["device_name"],
                    "status": "approved",
                    "expires_at": record["expires_at"],
                }
            except BaseException:
                connection.rollback()
                raise

    def poll_enrollment(self, device_code: str, verifier: str, *, now: int | None = None) -> dict[str, Any]:
        current = _now(now)
        with self.pool.connection() as connection:
            try:
                record = self._enrollment_by(
                    connection,
                    "e.device_code_hash = %s",
                    (_hash(device_code),),
                    for_update=True,
                )
                _validate_poll(record, verifier, current)
                if record["status"] == "pending":
                    connection.commit()
                    return {"status": "authorization_pending"}
                token, binding = _new_binding(record, current)
                tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, binding["tenant_id"])
                user_key = PostgreSQLIdentityResolver.user_id(connection, binding["user_id"])
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO platform_bridge_bindings(
                            binding_key, token_hash, channel, tenant_id, user_id,
                            visibility, display_label, device_name, created_at_epoch
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING binding_id
                        """,
                        (
                            binding["binding_id"], binding["token_hash"], binding["channel"], tenant_key,
                            user_key, binding["visibility"], binding["label"], binding["device_name"], binding["created_at"],
                        ),
                    )
                    binding_uuid = _value(cursor.fetchone(), "binding_id", 0)
                    cursor.execute(
                        """
                        UPDATE platform_bridge_enrollments
                        SET status = 'consumed', consumed_at_epoch = %s,
                            binding_id = %s, updated_at = now()
                        WHERE enrollment_id = %s AND status = 'approved' AND consumed_at_epoch IS NULL
                        """,
                        (current, binding_uuid, record["enrollment_uuid"]),
                    )
                    if cursor.rowcount != 1:
                        raise AuthenticationError("bridge_enrollment_already_consumed")
                connection.commit()
                return {"status": "authorized", "token": token, "binding": _binding_output(binding)}
            except BaseException:
                connection.rollback()
                raise

    def resolve_binding(self, token: str) -> dict[str, Any] | None:
        with self.pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(self._binding_select() + " WHERE b.token_hash = %s AND b.revoked_at_epoch IS NULL", (_hash(token),))
                row = cursor.fetchone()
        return self._binding_from_row(row) if row else None

    def list_bindings(self, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            user_key = PostgreSQLIdentityResolver.user_id(connection, user_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    self._binding_select() + " WHERE b.tenant_id = %s AND b.user_id = %s AND b.revoked_at_epoch IS NULL ORDER BY b.channel, b.created_at_epoch, b.binding_key",
                    (tenant_key, user_key),
                )
                rows = cursor.fetchall()
        return [self._binding_from_row(row) for row in rows]

    def revoke_binding(self, binding_id: str, tenant_id: str, user_id: str, *, now: int | None = None) -> bool:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            user_key = PostgreSQLIdentityResolver.user_id(connection, user_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_bridge_bindings
                    SET revoked_at_epoch = %s, updated_at = now()
                    WHERE binding_key = %s AND tenant_id = %s AND user_id = %s AND revoked_at_epoch IS NULL
                    """,
                    (_now(now), binding_id, tenant_key, user_key),
                )
                changed = cursor.rowcount == 1
            connection.commit()
        return changed

    @staticmethod
    def _enrollment_by(connection: Any, where: str, parameters: tuple[Any, ...], *, for_update: bool = False) -> dict[str, Any] | None:
        query = """
            SELECT e.enrollment_id AS enrollment_uuid, e.enrollment_key AS enrollment_id,
                   e.device_code_hash, e.user_code_hash, e.channel, e.device_name,
                   e.verifier_hash, e.status, t.tenant_code AS tenant_id,
                   u.external_subject AS user_id, a.external_subject AS approved_by,
                   e.expires_at_epoch AS expires_at, e.approved_at_epoch AS approved_at,
                   e.consumed_at_epoch AS consumed_at, e.created_at_epoch AS created_at,
                   b.binding_key AS binding_id
            FROM platform_bridge_enrollments e
            LEFT JOIN platform_tenants t ON t.tenant_id = e.tenant_id
            LEFT JOIN platform_user_profiles u ON u.user_id = e.user_id
            LEFT JOIN platform_user_profiles a ON a.user_id = e.approved_by
            LEFT JOIN platform_bridge_bindings b ON b.binding_id = e.binding_id
            WHERE """ + where + (" FOR UPDATE OF e" if for_update else "")
        with connection.cursor() as cursor:
            cursor.execute(query, parameters)
            row = cursor.fetchone()
        return dict(row) if isinstance(row, dict) else _enrollment_tuple(row) if row else None

    @staticmethod
    def _binding_select() -> str:
        return """
            SELECT b.binding_key AS binding_id, b.channel, t.tenant_code AS tenant_id,
                   u.external_subject AS user_id, b.visibility,
                   b.display_label AS label, b.device_name,
                   b.created_at_epoch AS created_at, b.revoked_at_epoch AS revoked_at
            FROM platform_bridge_bindings b
            JOIN platform_tenants t ON t.tenant_id = b.tenant_id
            JOIN platform_user_profiles u ON u.user_id = b.user_id
        """

    @staticmethod
    def _binding_from_row(row: Any) -> dict[str, Any]:
        if isinstance(row, dict):
            return _binding_output(row)
        keys = ("binding_id", "channel", "tenant_id", "user_id", "visibility", "label", "device_name", "created_at", "revoked_at")
        return _binding_output(dict(zip(keys, row)))


def _enrollment_tuple(row: Any) -> dict[str, Any]:
    keys = (
        "enrollment_uuid", "enrollment_id", "device_code_hash", "user_code_hash", "channel",
        "device_name", "verifier_hash", "status", "tenant_id", "user_id", "approved_by",
        "expires_at", "approved_at", "consumed_at", "created_at", "binding_id",
    )
    return dict(zip(keys, row))


def _is_unique_violation(exc: Exception) -> bool:
    sqlstate = str(getattr(exc, "sqlstate", "") or getattr(getattr(exc, "__cause__", None), "sqlstate", ""))
    return sqlstate == "23505" or isinstance(exc, sqlite3.IntegrityError)


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]
