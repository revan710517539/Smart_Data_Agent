from __future__ import annotations

import hashlib
import json
import time
from contextlib import contextmanager
from typing import Any, Iterator

from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.postgresql import PostgreSQLConnectionPool

from .oidc import OIDCTransaction, _new_transaction, _state_hash, _validate_transaction_record
from .secrets import decrypt_secret, encrypt_secret
from .session import AuthenticationError
from .session_store import (
    SessionGrant,
    _new_session_record,
    _replace_record_scope,
    _rotate_record,
    _token_hash,
    _validate_record,
    _validate_refresh_record,
)


class PostgreSQLSessionStore:
    """Concurrency-safe production session store with one-time refresh rotation."""

    def __init__(self, pool: PostgreSQLConnectionPool, *, owns_pool: bool = False) -> None:
        self.pool = pool
        self.owns_pool = owns_pool

    def close(self) -> None:
        if self.owns_pool:
            self.pool.close()

    def issue(self, user_id: str, primary_tenant_id: str, tenant_ids: tuple[str, ...], **kwargs: Any) -> SessionGrant:
        record, grant = _new_session_record(
            user_id,
            primary_tenant_id,
            tenant_ids,
            int(kwargs.get("access_ttl_seconds", 900)),
            int(kwargs.get("idle_timeout_seconds", 1800)),
            int(kwargs.get("absolute_timeout_seconds", 28_800)),
            kwargs.get("now"),
            str(kwargs.get("user_agent_hash") or ""),
            str(kwargs.get("ip_prefix") or ""),
        )
        with self._transaction() as connection:
            user_key = PostgreSQLIdentityResolver.user_id(connection, user_id)
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, primary_tenant_id)
            for tenant_code in record["tenant_ids"]:
                if tenant_code == "*":
                    continue
                PostgreSQLIdentityResolver.tenant_id(connection, str(tenant_code))
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_user_sessions(
                        tenant_id, user_id, device_session_key, access_jti,
                        refresh_token_hash, tenant_codes, user_agent_hash, ip_hash,
                        access_expires_at, idle_expires_at, expires_at,
                        idle_timeout_seconds, last_seen_at, created_by
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s::jsonb, %s, %s,
                        to_timestamp(%s), to_timestamp(%s), to_timestamp(%s),
                        %s, to_timestamp(%s), %s
                    )
                    """,
                    (
                        tenant_key,
                        user_key,
                        record["device_session_id"],
                        record["access_jti"],
                        record["refresh_token_hash"],
                        json.dumps(record["tenant_ids"], ensure_ascii=False),
                        record["user_agent_hash"] or None,
                        _optional_hash(record["ip_prefix"]),
                        record["access_expires_at"],
                        record["idle_expires_at"],
                        record["absolute_expires_at"],
                        record["idle_timeout_seconds"],
                        record["last_seen_at"],
                        user_key,
                    ),
                )
        return grant

    def validate_access(self, access_jti: str, device_session_id: str, user_id: str, tenant_id: str, **kwargs: Any) -> None:
        current = int(time.time() if kwargs.get("now") is None else kwargs["now"])
        with self._transaction() as connection:
            record = self._load_record(connection, "s.device_session_key = %s", (device_session_id,), for_update=True)
            _validate_record(record, access_jti, user_id, tenant_id, current)
            idle_expires_at = min(current + int(record["idle_timeout_seconds"]), int(record["absolute_expires_at"]))
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_user_sessions
                    SET last_seen_at = to_timestamp(%s), idle_expires_at = to_timestamp(%s),
                        updated_at = now(), lock_version = lock_version + 1
                    WHERE device_session_key = %s AND revoked_at IS NULL
                    """,
                    (current, idle_expires_at, device_session_id),
                )
                if cursor.rowcount != 1:
                    raise AuthenticationError("session_revoked_or_unknown")

    def rotate_refresh(self, refresh_token: str, **kwargs: Any) -> SessionGrant:
        current = int(time.time() if kwargs.get("now") is None else kwargs["now"])
        old_hash = _token_hash(refresh_token)
        with self._transaction() as connection:
            record = self._load_record(connection, "s.refresh_token_hash = %s", (old_hash,), for_update=True)
            _validate_refresh_record(record, current)
            _replace_record_scope(
                record,
                primary_tenant_id=kwargs.get("primary_tenant_id"),
                tenant_ids=kwargs.get("tenant_ids"),
            )
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, record["primary_tenant_id"])
            for tenant_code in record["tenant_ids"]:
                if tenant_code == "*":
                    continue
                PostgreSQLIdentityResolver.tenant_id(connection, str(tenant_code))
            grant = _rotate_record(record, int(kwargs.get("access_ttl_seconds", 900)), current)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_user_sessions
                    SET tenant_id = %s, tenant_codes = %s::jsonb,
                        access_jti = %s, refresh_token_hash = %s,
                        access_expires_at = to_timestamp(%s), last_seen_at = to_timestamp(%s),
                        idle_expires_at = to_timestamp(%s), rotated_at = to_timestamp(%s),
                        updated_at = now(), lock_version = lock_version + 1
                    WHERE device_session_key = %s AND refresh_token_hash = %s AND revoked_at IS NULL
                    """,
                    (
                        tenant_key, json.dumps(record["tenant_ids"], ensure_ascii=False),
                        record["access_jti"], record["refresh_token_hash"], record["access_expires_at"],
                        record["last_seen_at"], record["idle_expires_at"], current,
                        record["device_session_id"], old_hash,
                    ),
                )
                if cursor.rowcount != 1:
                    raise AuthenticationError("refresh_token_already_rotated")
        return grant

    def resolve_refresh(self, refresh_token: str, **kwargs: Any) -> SessionGrant:
        current = int(time.time() if kwargs.get("now") is None else kwargs["now"])
        with self._transaction() as connection:
            record = self._load_record(
                connection,
                "s.refresh_token_hash = %s",
                (_token_hash(refresh_token),),
                for_update=False,
            )
            _validate_refresh_record(record, current)
            return SessionGrant(
                device_session_id=str(record["device_session_id"]),
                access_jti=str(record["access_jti"]),
                refresh_token=refresh_token,
                user_id=str(record["user_id"]),
                primary_tenant_id=str(record["primary_tenant_id"]),
                tenant_ids=tuple(record["tenant_ids"]),
                issued_at=int(record["issued_at"]),
                access_expires_at=int(record["access_expires_at"]),
                idle_expires_at=int(record["idle_expires_at"]),
                absolute_expires_at=int(record["absolute_expires_at"]),
            )

    def revoke(
        self,
        *,
        access_jti: str = "",
        refresh_token: str = "",
        reason: str = "logout",
        now: int | None = None,
    ) -> bool:
        if not access_jti and not refresh_token:
            return False
        clauses: list[str] = []
        params: list[Any] = [int(time.time() if now is None else now), str(reason or "logout")[:200]]
        if access_jti:
            clauses.append("access_jti = %s")
            params.append(access_jti)
        if refresh_token:
            clauses.append("refresh_token_hash = %s")
            params.append(_token_hash(refresh_token))
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE platform_user_sessions
                SET revoked_at = to_timestamp(%s), revoke_reason = %s,
                    updated_at = now(), lock_version = lock_version + 1
                WHERE ({' OR '.join(clauses)}) AND revoked_at IS NULL
                """,
                tuple(params),
            )
            return cursor.rowcount > 0

    def revoke_user(self, user_id: str, reason: str = "user_disabled", now: int | None = None) -> int:
        with self._transaction() as connection:
            user_key = PostgreSQLIdentityResolver.user_id(connection, user_id, required=False)
            if user_key is None:
                return 0
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_user_sessions
                    SET revoked_at = to_timestamp(%s), revoke_reason = %s,
                        updated_at = now(), lock_version = lock_version + 1
                    WHERE user_id = %s AND revoked_at IS NULL
                    """,
                    (int(time.time() if now is None else now), str(reason or "user_disabled")[:200], user_key),
                )
                return int(cursor.rowcount)

    @staticmethod
    def _load_record(connection: Any, where: str, params: tuple[Any, ...], *, for_update: bool) -> dict[str, Any] | None:
        suffix = " FOR UPDATE" if for_update else ""
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT s.device_session_key, s.access_jti, s.refresh_token_hash,
                       u.external_subject AS user_code, t.tenant_code AS primary_tenant_code,
                       s.tenant_codes,
                       EXTRACT(EPOCH FROM s.created_at)::bigint AS issued_at,
                       EXTRACT(EPOCH FROM s.access_expires_at)::bigint AS access_expires_at,
                       EXTRACT(EPOCH FROM s.last_seen_at)::bigint AS last_seen_at,
                       EXTRACT(EPOCH FROM s.idle_expires_at)::bigint AS idle_expires_at,
                       EXTRACT(EPOCH FROM s.expires_at)::bigint AS absolute_expires_at,
                       s.idle_timeout_seconds,
                       EXTRACT(EPOCH FROM s.revoked_at)::bigint AS revoked_at,
                       s.revoke_reason,
                       EXTRACT(EPOCH FROM s.rotated_at)::bigint AS rotated_at,
                       s.user_agent_hash, s.ip_hash
                FROM platform_user_sessions s
                JOIN platform_user_profiles u ON u.user_id = s.user_id
                JOIN platform_tenants t ON t.tenant_id = s.tenant_id
                WHERE {where}{suffix}
                """,
                params,
            )
            row = cursor.fetchone()
        if not row:
            return None
        tenant_codes = _value(row, "tenant_codes", 5)
        if isinstance(tenant_codes, str):
            tenant_codes = json.loads(tenant_codes)
        return {
            "device_session_id": str(_value(row, "device_session_key", 0)),
            "access_jti": str(_value(row, "access_jti", 1)),
            "refresh_token_hash": str(_value(row, "refresh_token_hash", 2)),
            "user_id": str(_value(row, "user_code", 3)),
            "primary_tenant_id": str(_value(row, "primary_tenant_code", 4)),
            "tenant_ids": list(tenant_codes or []),
            "issued_at": int(_value(row, "issued_at", 6)),
            "access_expires_at": int(_value(row, "access_expires_at", 7)),
            "last_seen_at": int(_value(row, "last_seen_at", 8)),
            "idle_expires_at": int(_value(row, "idle_expires_at", 9)),
            "absolute_expires_at": int(_value(row, "absolute_expires_at", 10)),
            "idle_timeout_seconds": int(_value(row, "idle_timeout_seconds", 11)),
            "revoked_at": _optional_int(_value(row, "revoked_at", 12)),
            "revoke_reason": str(_value(row, "revoke_reason", 13) or ""),
            "rotated_at": _optional_int(_value(row, "rotated_at", 14)),
            "user_agent_hash": str(_value(row, "user_agent_hash", 15) or ""),
            "ip_prefix": "",
        }

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self.pool.connection() as connection:
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise


class PostgreSQLOIDCTransactionStore:
    """One-time OIDC state/nonce/PKCE store; state is hashed and PKCE is encrypted."""

    def __init__(self, pool: PostgreSQLConnectionPool, *, owns_pool: bool = False) -> None:
        self.pool = pool
        self.owns_pool = owns_pool

    def close(self) -> None:
        if self.owns_pool:
            self.pool.close()

    def create(self, redirect_uri: str, ttl_seconds: int = 300, now: int | None = None) -> OIDCTransaction:
        transaction, record = _new_transaction(redirect_uri, ttl_seconds, now)
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO platform_oidc_transactions(
                    transaction_key, state_hash, nonce, code_verifier_ciphertext,
                    redirect_uri, expires_at
                ) VALUES (%s, %s, %s, %s, %s, to_timestamp(%s))
                """,
                (
                    transaction.transaction_id, record["state_hash"], transaction.nonce,
                    encrypt_secret(transaction.code_verifier), transaction.redirect_uri,
                    transaction.expires_at,
                ),
            )
        return transaction

    def consume(self, state: str, now: int | None = None) -> OIDCTransaction:
        current = int(time.time() if now is None else now)
        state_hash = _state_hash(state)
        with self._transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT transaction_key, state_hash, nonce, code_verifier_ciphertext,
                           redirect_uri, EXTRACT(EPOCH FROM expires_at)::bigint AS expires_at,
                           EXTRACT(EPOCH FROM consumed_at)::bigint AS consumed_at
                    FROM platform_oidc_transactions
                    WHERE state_hash = %s
                    FOR UPDATE
                    """,
                    (state_hash,),
                )
                row = cursor.fetchone()
            record = None
            if row:
                record = {
                    "transaction_id": str(_value(row, "transaction_key", 0)),
                    "state_hash": str(_value(row, "state_hash", 1)),
                    "nonce": str(_value(row, "nonce", 2)),
                    "code_verifier": decrypt_secret(str(_value(row, "code_verifier_ciphertext", 3))),
                    "redirect_uri": str(_value(row, "redirect_uri", 4)),
                    "expires_at": int(_value(row, "expires_at", 5)),
                    "consumed_at": _optional_int(_value(row, "consumed_at", 6)),
                }
            transaction = _validate_transaction_record(record, state, current)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_oidc_transactions
                    SET consumed_at = to_timestamp(%s), updated_at = now(),
                        lock_version = lock_version + 1
                    WHERE state_hash = %s AND consumed_at IS NULL AND expires_at > to_timestamp(%s)
                    """,
                    (current, state_hash, current),
                )
                if cursor.rowcount != 1:
                    raise AuthenticationError("oidc_transaction_already_consumed")
        return transaction

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self.pool.connection() as connection:
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise


def _optional_hash(value: str) -> str | None:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]
