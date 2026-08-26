from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from backend.platform.storage import connect_sqlite

from .session import AuthenticationError


@dataclass(frozen=True)
class SessionGrant:
    device_session_id: str
    access_jti: str
    refresh_token: str
    user_id: str
    primary_tenant_id: str
    tenant_ids: tuple[str, ...]
    issued_at: int
    access_expires_at: int
    idle_expires_at: int
    absolute_expires_at: int


class SessionStore(Protocol):
    def issue(self, user_id: str, primary_tenant_id: str, tenant_ids: tuple[str, ...], **kwargs) -> SessionGrant:
        ...

    def validate_access(self, access_jti: str, device_session_id: str, user_id: str, tenant_id: str, **kwargs) -> None:
        ...

    def rotate_refresh(self, refresh_token: str, **kwargs) -> SessionGrant:
        ...

    def resolve_refresh(self, refresh_token: str, **kwargs) -> SessionGrant:
        ...

    def revoke(self, *, access_jti: str = "", refresh_token: str = "", reason: str = "logout", now: int | None = None) -> bool:
        ...

    def revoke_user(self, user_id: str, reason: str = "user_disabled", now: int | None = None) -> int:
        ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}
        self._lock = threading.RLock()

    def close(self) -> None:
        return None

    def issue(
        self,
        user_id: str,
        primary_tenant_id: str,
        tenant_ids: tuple[str, ...],
        *,
        access_ttl_seconds: int = 900,
        idle_timeout_seconds: int = 1800,
        absolute_timeout_seconds: int = 28_800,
        now: int | None = None,
        user_agent_hash: str = "",
        ip_prefix: str = "",
    ) -> SessionGrant:
        record, grant = _new_session_record(
            user_id,
            primary_tenant_id,
            tenant_ids,
            access_ttl_seconds,
            idle_timeout_seconds,
            absolute_timeout_seconds,
            now,
            user_agent_hash,
            ip_prefix,
        )
        with self._lock:
            self._sessions[grant.device_session_id] = record
        return grant

    def validate_access(
        self,
        access_jti: str,
        device_session_id: str,
        user_id: str,
        tenant_id: str,
        *,
        now: int | None = None,
    ) -> None:
        current = int(time.time() if now is None else now)
        with self._lock:
            record = self._sessions.get(device_session_id)
            _validate_record(record, access_jti, user_id, tenant_id, current)
            record["last_seen_at"] = current
            record["idle_expires_at"] = min(
                current + int(record["idle_timeout_seconds"]),
                int(record["absolute_expires_at"]),
            )

    def rotate_refresh(
        self,
        refresh_token: str,
        *,
        access_ttl_seconds: int = 900,
        now: int | None = None,
        primary_tenant_id: str | None = None,
        tenant_ids: tuple[str, ...] | None = None,
    ) -> SessionGrant:
        current = int(time.time() if now is None else now)
        refresh_hash = _token_hash(refresh_token)
        with self._lock:
            record = next((item for item in self._sessions.values() if item["refresh_token_hash"] == refresh_hash), None)
            _validate_refresh_record(record, current)
            _replace_record_scope(
                record,
                primary_tenant_id=primary_tenant_id,
                tenant_ids=tenant_ids,
            )
            return _rotate_record(record, access_ttl_seconds, current)

    def resolve_refresh(self, refresh_token: str, *, now: int | None = None) -> SessionGrant:
        current = int(time.time() if now is None else now)
        refresh_hash = _token_hash(refresh_token)
        with self._lock:
            record = next((item for item in self._sessions.values() if item["refresh_token_hash"] == refresh_hash), None)
            _validate_refresh_record(record, current)
            return _grant(record, refresh_token)

    def revoke(
        self,
        *,
        access_jti: str = "",
        refresh_token: str = "",
        reason: str = "logout",
        now: int | None = None,
    ) -> bool:
        current = int(time.time() if now is None else now)
        refresh_hash = _token_hash(refresh_token) if refresh_token else ""
        with self._lock:
            record = next(
                (
                    item
                    for item in self._sessions.values()
                    if (access_jti and item["access_jti"] == access_jti)
                    or (refresh_hash and item["refresh_token_hash"] == refresh_hash)
                ),
                None,
            )
            if not record:
                return False
            record["revoked_at"] = current
            record["revoke_reason"] = reason
            return True

    def revoke_user(self, user_id: str, reason: str = "user_disabled", now: int | None = None) -> int:
        current = int(time.time() if now is None else now)
        count = 0
        with self._lock:
            for record in self._sessions.values():
                if record["user_id"] == user_id and record.get("revoked_at") is None:
                    record["revoked_at"] = current
                    record["revoke_reason"] = reason
                    count += 1
        return count


class SQLiteSessionStore:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = connect_sqlite(str(db_path))
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def issue(self, user_id: str, primary_tenant_id: str, tenant_ids: tuple[str, ...], **kwargs) -> SessionGrant:
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
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_auth_sessions(
                    device_session_id, access_jti, refresh_token_hash, user_id,
                    primary_tenant_id, tenant_ids, issued_at, access_expires_at,
                    last_seen_at, idle_expires_at, absolute_expires_at,
                    idle_timeout_seconds, user_agent_hash, ip_prefix
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["device_session_id"], record["access_jti"], record["refresh_token_hash"],
                    record["user_id"], record["primary_tenant_id"], json.dumps(record["tenant_ids"]),
                    record["issued_at"], record["access_expires_at"], record["last_seen_at"],
                    record["idle_expires_at"], record["absolute_expires_at"], record["idle_timeout_seconds"],
                    record["user_agent_hash"], record["ip_prefix"],
                ),
            )
        return grant

    def validate_access(self, access_jti: str, device_session_id: str, user_id: str, tenant_id: str, **kwargs) -> None:
        current = int(time.time() if kwargs.get("now") is None else kwargs["now"])
        row = self._conn.execute(
            "SELECT * FROM platform_auth_sessions WHERE device_session_id = ?",
            (device_session_id,),
        ).fetchone()
        record = _record_from_row(row) if row else None
        _validate_record(record, access_jti, user_id, tenant_id, current)
        idle_expires_at = min(current + int(record["idle_timeout_seconds"]), int(record["absolute_expires_at"]))
        with self._conn:
            self._conn.execute(
                "UPDATE platform_auth_sessions SET last_seen_at = ?, idle_expires_at = ? WHERE device_session_id = ?",
                (current, idle_expires_at, device_session_id),
            )

    def rotate_refresh(self, refresh_token: str, **kwargs) -> SessionGrant:
        current = int(time.time() if kwargs.get("now") is None else kwargs["now"])
        row = self._conn.execute(
            "SELECT * FROM platform_auth_sessions WHERE refresh_token_hash = ?",
            (_token_hash(refresh_token),),
        ).fetchone()
        record = _record_from_row(row) if row else None
        _validate_refresh_record(record, current)
        _replace_record_scope(
            record,
            primary_tenant_id=kwargs.get("primary_tenant_id"),
            tenant_ids=kwargs.get("tenant_ids"),
        )
        grant = _rotate_record(record, int(kwargs.get("access_ttl_seconds", 900)), current)
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE platform_auth_sessions
                SET primary_tenant_id = ?, tenant_ids = ?,
                    access_jti = ?, refresh_token_hash = ?, access_expires_at = ?,
                    last_seen_at = ?, idle_expires_at = ?, rotated_at = ?
                WHERE device_session_id = ? AND refresh_token_hash = ? AND revoked_at IS NULL
                """,
                (
                    record["primary_tenant_id"], json.dumps(record["tenant_ids"]),
                    record["access_jti"], record["refresh_token_hash"], record["access_expires_at"],
                    record["last_seen_at"], record["idle_expires_at"], current,
                    record["device_session_id"], _token_hash(refresh_token),
                ),
            )
            if cursor.rowcount != 1:
                raise AuthenticationError("refresh_token_already_rotated")
        return grant

    def resolve_refresh(self, refresh_token: str, **kwargs) -> SessionGrant:
        current = int(time.time() if kwargs.get("now") is None else kwargs["now"])
        row = self._conn.execute(
            "SELECT * FROM platform_auth_sessions WHERE refresh_token_hash = ?",
            (_token_hash(refresh_token),),
        ).fetchone()
        record = _record_from_row(row) if row else None
        _validate_refresh_record(record, current)
        return _grant(record, refresh_token)

    def revoke(self, *, access_jti: str = "", refresh_token: str = "", reason: str = "logout", now: int | None = None) -> bool:
        current = int(time.time() if now is None else now)
        clauses: list[str] = []
        params: list[str | int] = [current, reason]
        if access_jti:
            clauses.append("access_jti = ?")
            params.append(access_jti)
        if refresh_token:
            clauses.append("refresh_token_hash = ?")
            params.append(_token_hash(refresh_token))
        if not clauses:
            return False
        with self._conn:
            cursor = self._conn.execute(
                f"UPDATE platform_auth_sessions SET revoked_at = ?, revoke_reason = ? WHERE ({' OR '.join(clauses)}) AND revoked_at IS NULL",
                tuple(params),
            )
        return cursor.rowcount > 0

    def revoke_user(self, user_id: str, reason: str = "user_disabled", now: int | None = None) -> int:
        current = int(time.time() if now is None else now)
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE platform_auth_sessions SET revoked_at = ?, revoke_reason = ? WHERE user_id = ? AND revoked_at IS NULL",
                (current, reason, user_id),
            )
        return int(cursor.rowcount)


def _new_session_record(
    user_id: str,
    primary_tenant_id: str,
    tenant_ids: tuple[str, ...],
    access_ttl_seconds: int,
    idle_timeout_seconds: int,
    absolute_timeout_seconds: int,
    now: int | None,
    user_agent_hash: str,
    ip_prefix: str,
) -> tuple[dict, SessionGrant]:
    current = int(time.time() if now is None else now)
    if access_ttl_seconds < 60 or idle_timeout_seconds < 60 or absolute_timeout_seconds < idle_timeout_seconds:
        raise ValueError("invalid_session_timeout_policy")
    normalized_tenants = tuple(dict.fromkeys((primary_tenant_id, *tenant_ids)))
    device_session_id = "ds_" + secrets.token_urlsafe(24)
    access_jti = "at_" + secrets.token_urlsafe(24)
    refresh_token = "rt_" + secrets.token_urlsafe(40)
    absolute_expires_at = current + absolute_timeout_seconds
    record = {
        "device_session_id": device_session_id,
        "access_jti": access_jti,
        "refresh_token_hash": _token_hash(refresh_token),
        "user_id": user_id,
        "primary_tenant_id": primary_tenant_id,
        "tenant_ids": list(normalized_tenants),
        "issued_at": current,
        "access_expires_at": min(current + access_ttl_seconds, absolute_expires_at),
        "last_seen_at": current,
        "idle_expires_at": min(current + idle_timeout_seconds, absolute_expires_at),
        "absolute_expires_at": absolute_expires_at,
        "idle_timeout_seconds": idle_timeout_seconds,
        "revoked_at": None,
        "revoke_reason": "",
        "rotated_at": None,
        "user_agent_hash": user_agent_hash,
        "ip_prefix": ip_prefix,
    }
    return record, _grant(record, refresh_token)


def _rotate_record(record: dict, access_ttl_seconds: int, current: int) -> SessionGrant:
    refresh_token = "rt_" + secrets.token_urlsafe(40)
    record["access_jti"] = "at_" + secrets.token_urlsafe(24)
    record["refresh_token_hash"] = _token_hash(refresh_token)
    record["access_expires_at"] = min(current + access_ttl_seconds, int(record["absolute_expires_at"]))
    record["last_seen_at"] = current
    record["idle_expires_at"] = min(current + int(record["idle_timeout_seconds"]), int(record["absolute_expires_at"]))
    record["rotated_at"] = current
    return _grant(record, refresh_token)


def _replace_record_scope(
    record: dict,
    *,
    primary_tenant_id: object = None,
    tenant_ids: object = None,
) -> None:
    if primary_tenant_id is None and tenant_ids is None:
        return
    primary = str(primary_tenant_id or record.get("primary_tenant_id") or "").strip()
    if not primary or primary == "*":
        raise ValueError("invalid_primary_session_tenant")
    raw_tenants = (record.get("tenant_ids") or []) if tenant_ids is None else tenant_ids
    if isinstance(raw_tenants, str):
        raw_tenants = (raw_tenants,)
    normalized = tuple(
        dict.fromkeys(
            item
            for item in (primary, *(str(value or "").strip() for value in raw_tenants))
            if item
        )
    )
    record["primary_tenant_id"] = primary
    record["tenant_ids"] = list(normalized)


def _grant(record: dict, refresh_token: str) -> SessionGrant:
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


def _validate_record(record: dict | None, access_jti: str, user_id: str, tenant_id: str, current: int) -> None:
    if not record or record.get("revoked_at") is not None:
        raise AuthenticationError("session_revoked_or_unknown")
    if record["access_jti"] != access_jti or record["user_id"] != user_id:
        raise AuthenticationError("session_identity_mismatch")
    if tenant_id not in record["tenant_ids"]:
        raise AuthenticationError("session_tenant_not_allowed")
    if current >= int(record["access_expires_at"]):
        raise AuthenticationError("access_session_expired")
    if current >= int(record["idle_expires_at"]):
        raise AuthenticationError("session_idle_timeout")
    if current >= int(record["absolute_expires_at"]):
        raise AuthenticationError("session_absolute_timeout")


def _validate_refresh_record(record: dict | None, current: int) -> None:
    if not record or record.get("revoked_at") is not None:
        raise AuthenticationError("refresh_session_revoked_or_unknown")
    if current >= int(record["absolute_expires_at"]):
        raise AuthenticationError("session_absolute_timeout")
    if current >= int(record["idle_expires_at"]):
        raise AuthenticationError("session_idle_timeout")


def _record_from_row(row: sqlite3.Row) -> dict:
    return {
        **dict(row),
        "tenant_ids": json.loads(row["tenant_ids"] or "[]"),
    }


def _token_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()
