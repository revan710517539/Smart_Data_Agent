from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Protocol

from backend.platform.security import AuthenticationError
from backend.platform.storage import connect_sqlite


BRIDGE_CHANNELS = frozenset({"workbuddy", "codex", "qwork"})
DEFAULT_ENROLLMENT_TTL_SECONDS = 600
_USER_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


class BridgeAuthStore(Protocol):
    def start_enrollment(
        self,
        channel: str,
        device_name: str,
        verifier_hash: str,
        *,
        now: int | None = None,
        ttl_seconds: int = DEFAULT_ENROLLMENT_TTL_SECONDS,
    ) -> dict[str, Any]: ...

    def enrollment_preview(self, user_code: str, *, now: int | None = None) -> dict[str, Any]: ...

    def approve_enrollment(
        self,
        user_code: str,
        tenant_id: str,
        user_id: str,
        approved_by: str,
        *,
        now: int | None = None,
    ) -> dict[str, Any]: ...

    def poll_enrollment(
        self,
        device_code: str,
        verifier: str,
        *,
        now: int | None = None,
    ) -> dict[str, Any]: ...

    def resolve_binding(self, token: str) -> dict[str, Any] | None: ...

    def list_bindings(self, tenant_id: str, user_id: str) -> list[dict[str, Any]]: ...

    def revoke_binding(
        self,
        binding_id: str,
        tenant_id: str,
        user_id: str,
        *,
        now: int | None = None,
    ) -> bool: ...

    def close(self) -> None: ...


class InMemoryBridgeAuthStore:
    def __init__(self) -> None:
        self._enrollments: dict[str, dict[str, Any]] = {}
        self._bindings: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def close(self) -> None:
        return None

    def start_enrollment(self, channel: str, device_name: str, verifier_hash: str, **kwargs: Any) -> dict[str, Any]:
        current, expires_at = _enrollment_window(kwargs.get("now"), kwargs.get("ttl_seconds", DEFAULT_ENROLLMENT_TTL_SECONDS))
        normalized_channel = _channel(channel)
        normalized_verifier_hash = _verifier_hash(verifier_hash)
        with self._lock:
            enrollment = _new_enrollment(normalized_channel, device_name, normalized_verifier_hash, current, expires_at)
            while enrollment["user_code_hash"] in {item["user_code_hash"] for item in self._enrollments.values()}:
                enrollment = _new_enrollment(normalized_channel, device_name, normalized_verifier_hash, current, expires_at)
            self._enrollments[enrollment["device_code_hash"]] = enrollment
        return _start_result(enrollment)

    def enrollment_preview(self, user_code: str, *, now: int | None = None) -> dict[str, Any]:
        current = _now(now)
        with self._lock:
            record = self._by_user_code(user_code)
            _validate_enrollment_available(record, current)
            return _preview(record)

    def approve_enrollment(self, user_code: str, tenant_id: str, user_id: str, approved_by: str, *, now: int | None = None) -> dict[str, Any]:
        current = _now(now)
        with self._lock:
            record = self._by_user_code(user_code)
            _validate_enrollment_available(record, current)
            if record["status"] == "approved":
                if record["tenant_id"] != tenant_id or record["user_id"] != user_id:
                    raise PermissionError("bridge_enrollment_already_approved")
                return _preview(record)
            record.update({
                "status": "approved",
                "tenant_id": _required(tenant_id, "bridge_enrollment_tenant_required"),
                "user_id": _required(user_id, "bridge_enrollment_user_required"),
                "approved_by": _required(approved_by, "bridge_enrollment_approver_required"),
                "approved_at": current,
            })
            return _preview(record)

    def poll_enrollment(self, device_code: str, verifier: str, *, now: int | None = None) -> dict[str, Any]:
        current = _now(now)
        with self._lock:
            record = self._enrollments.get(_hash(device_code))
            return _poll_and_consume(record, verifier, current, self._bindings)

    def resolve_binding(self, token: str) -> dict[str, Any] | None:
        token_hash = _hash(token)
        with self._lock:
            record = next((item for item in self._bindings.values() if hmac.compare_digest(item["token_hash"], token_hash)), None)
            return _binding_output(record) if record and record.get("revoked_at") is None else None

    def list_bindings(self, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
        with self._lock:
            records = [
                _binding_output(item)
                for item in self._bindings.values()
                if item["tenant_id"] == tenant_id and item["user_id"] == user_id and item.get("revoked_at") is None
            ]
        return sorted(records, key=lambda item: (item["channel"], item["created_at"], item["binding_id"]))

    def revoke_binding(self, binding_id: str, tenant_id: str, user_id: str, *, now: int | None = None) -> bool:
        with self._lock:
            record = self._bindings.get(binding_id)
            if not record or record["tenant_id"] != tenant_id or record["user_id"] != user_id or record.get("revoked_at") is not None:
                return False
            record["revoked_at"] = _now(now)
            return True

    def _by_user_code(self, user_code: str) -> dict[str, Any] | None:
        target = _user_code_hash(user_code)
        return next((item for item in self._enrollments.values() if hmac.compare_digest(item["user_code_hash"], target)), None)


class SQLiteBridgeAuthStore:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = connect_sqlite(str(db_path))
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def start_enrollment(self, channel: str, device_name: str, verifier_hash: str, **kwargs: Any) -> dict[str, Any]:
        current, expires_at = _enrollment_window(kwargs.get("now"), kwargs.get("ttl_seconds", DEFAULT_ENROLLMENT_TTL_SECONDS))
        normalized_channel = _channel(channel)
        normalized_verifier_hash = _verifier_hash(verifier_hash)
        for _ in range(5):
            enrollment = _new_enrollment(normalized_channel, device_name, normalized_verifier_hash, current, expires_at)
            try:
                with self._conn:
                    self._conn.execute(
                        """
                        INSERT INTO platform_bridge_enrollments(
                            enrollment_id, device_code_hash, user_code_hash, channel,
                            device_name, verifier_hash, status, expires_at, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                        """,
                        (
                            enrollment["enrollment_id"], enrollment["device_code_hash"], enrollment["user_code_hash"],
                            enrollment["channel"], enrollment["device_name"], enrollment["verifier_hash"],
                            enrollment["expires_at"], enrollment["created_at"],
                        ),
                    )
                return _start_result(enrollment)
            except sqlite3.IntegrityError:
                continue
        raise RuntimeError("bridge_enrollment_code_generation_failed")

    def enrollment_preview(self, user_code: str, *, now: int | None = None) -> dict[str, Any]:
        record = self._conn.execute(
            "SELECT * FROM platform_bridge_enrollments WHERE user_code_hash = ?",
            (_user_code_hash(user_code),),
        ).fetchone()
        _validate_enrollment_available(record, _now(now))
        return _preview(record)

    def approve_enrollment(self, user_code: str, tenant_id: str, user_id: str, approved_by: str, *, now: int | None = None) -> dict[str, Any]:
        current = _now(now)
        with self._conn:
            record = self._conn.execute(
                "SELECT * FROM platform_bridge_enrollments WHERE user_code_hash = ?",
                (_user_code_hash(user_code),),
            ).fetchone()
            _validate_enrollment_available(record, current)
            if record["status"] == "approved":
                if record["tenant_id"] != tenant_id or record["user_id"] != user_id:
                    raise PermissionError("bridge_enrollment_already_approved")
                return _preview(record)
            self._conn.execute(
                """
                UPDATE platform_bridge_enrollments
                SET status = 'approved', tenant_id = ?, user_id = ?, approved_by = ?, approved_at = ?
                WHERE enrollment_id = ? AND status = 'pending' AND consumed_at IS NULL
                """,
                (
                    _required(tenant_id, "bridge_enrollment_tenant_required"),
                    _required(user_id, "bridge_enrollment_user_required"),
                    _required(approved_by, "bridge_enrollment_approver_required"),
                    current,
                    record["enrollment_id"],
                ),
            )
            updated = self._conn.execute(
                "SELECT * FROM platform_bridge_enrollments WHERE enrollment_id = ?",
                (record["enrollment_id"],),
            ).fetchone()
        return _preview(updated)

    def poll_enrollment(self, device_code: str, verifier: str, *, now: int | None = None) -> dict[str, Any]:
        current = _now(now)
        device_code_hash = _hash(device_code)
        with self._conn:
            record = self._conn.execute(
                "SELECT * FROM platform_bridge_enrollments WHERE device_code_hash = ?",
                (device_code_hash,),
            ).fetchone()
            _validate_poll(record, verifier, current)
            if record["status"] == "pending":
                return {"status": "authorization_pending"}
            token, binding = _new_binding(record, current)
            self._conn.execute(
                """
                INSERT INTO platform_bridge_bindings(
                    binding_id, token_hash, channel, tenant_id, user_id,
                    visibility, label, device_name, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    binding["binding_id"], binding["token_hash"], binding["channel"], binding["tenant_id"],
                    binding["user_id"], binding["visibility"], binding["label"], binding["device_name"], binding["created_at"],
                ),
            )
            updated = self._conn.execute(
                """
                UPDATE platform_bridge_enrollments
                SET status = 'consumed', consumed_at = ?, binding_id = ?
                WHERE enrollment_id = ? AND status = 'approved' AND consumed_at IS NULL
                """,
                (current, binding["binding_id"], record["enrollment_id"]),
            )
            if updated.rowcount != 1:
                raise AuthenticationError("bridge_enrollment_already_consumed")
        return {"status": "authorized", "token": token, "binding": _binding_output(binding)}

    def resolve_binding(self, token: str) -> dict[str, Any] | None:
        record = self._conn.execute(
            "SELECT * FROM platform_bridge_bindings WHERE token_hash = ? AND revoked_at IS NULL",
            (_hash(token),),
        ).fetchone()
        return _binding_output(record) if record else None

    def list_bindings(self, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT * FROM platform_bridge_bindings
            WHERE tenant_id = ? AND user_id = ? AND revoked_at IS NULL
            ORDER BY channel, created_at, binding_id
            """,
            (tenant_id, user_id),
        ).fetchall()
        return [_binding_output(row) for row in rows]

    def revoke_binding(self, binding_id: str, tenant_id: str, user_id: str, *, now: int | None = None) -> bool:
        with self._conn:
            result = self._conn.execute(
                """
                UPDATE platform_bridge_bindings SET revoked_at = ?
                WHERE binding_id = ? AND tenant_id = ? AND user_id = ? AND revoked_at IS NULL
                """,
                (_now(now), binding_id, tenant_id, user_id),
            )
        return result.rowcount == 1


def _new_enrollment(channel: str, device_name: str, verifier_hash: str, current: int, expires_at: int) -> dict[str, Any]:
    device_code = secrets.token_urlsafe(32)
    compact_code = "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(8))
    user_code = f"{compact_code[:4]}-{compact_code[4:]}"
    return {
        "enrollment_id": f"bridge_enroll_{uuid.uuid4().hex}",
        "device_code": device_code,
        "device_code_hash": _hash(device_code),
        "user_code": user_code,
        "user_code_hash": _user_code_hash(user_code),
        "channel": channel,
        "device_name": str(device_name or "").strip()[:160] or f"{channel} device",
        "verifier_hash": verifier_hash,
        "status": "pending",
        "tenant_id": "",
        "user_id": "",
        "approved_by": "",
        "expires_at": expires_at,
        "approved_at": None,
        "consumed_at": None,
        "binding_id": "",
        "created_at": current,
    }


def _start_result(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "device_code": record["device_code"],
        "user_code": record["user_code"],
        "channel": record["channel"],
        "device_name": record["device_name"],
        "expires_at": int(record["expires_at"]),
        "expires_in": max(0, int(record["expires_at"]) - int(record["created_at"])),
        "interval": 2,
    }


def _preview(record: Any) -> dict[str, Any]:
    return {
        "channel": str(record["channel"]),
        "device_name": str(record["device_name"]),
        "status": str(record["status"]),
        "expires_at": int(record["expires_at"]),
    }


def _poll_and_consume(record: dict[str, Any] | None, verifier: str, current: int, bindings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    _validate_poll(record, verifier, current)
    if record["status"] == "pending":
        return {"status": "authorization_pending"}
    token, binding = _new_binding(record, current)
    bindings[binding["binding_id"]] = binding
    record.update({"status": "consumed", "consumed_at": current, "binding_id": binding["binding_id"]})
    return {"status": "authorized", "token": token, "binding": _binding_output(binding)}


def _new_binding(record: Any, current: int) -> tuple[str, dict[str, Any]]:
    token = secrets.token_urlsafe(48)
    channel = str(record["channel"])
    binding = {
        "binding_id": f"bridge_{channel}_{uuid.uuid4().hex}",
        "token_hash": _hash(token),
        "channel": channel,
        "tenant_id": str(record["tenant_id"]),
        "user_id": str(record["user_id"]),
        "visibility": "private",
        "label": {"workbuddy": "WorkBuddy", "codex": "Codex", "qwork": "QWork"}[channel],
        "device_name": str(record["device_name"]),
        "created_at": current,
        "revoked_at": None,
    }
    return token, binding


def _binding_output(record: Any) -> dict[str, Any]:
    return {
        "binding_id": str(record["binding_id"]),
        "channel": str(record["channel"]),
        "tenant_id": str(record["tenant_id"]),
        "user_id": str(record["user_id"]),
        "visibility": str(record["visibility"] or "private"),
        "label": str(record["label"] or record["channel"]),
        "device_name": str(record["device_name"] or ""),
        "created_at": int(record["created_at"] or 0),
        "revoked_at": int(record["revoked_at"]) if record["revoked_at"] is not None else None,
    }


def _validate_enrollment_available(record: Any, current: int) -> None:
    if record is None:
        raise AuthenticationError("bridge_enrollment_unknown")
    if int(record["expires_at"]) <= current:
        raise AuthenticationError("bridge_enrollment_expired")
    if record["status"] == "consumed" or record["consumed_at"] is not None:
        raise AuthenticationError("bridge_enrollment_already_consumed")


def _validate_poll(record: Any, verifier: str, current: int) -> None:
    _validate_enrollment_available(record, current)
    if not hmac.compare_digest(str(record["verifier_hash"]), _hash(verifier)):
        raise AuthenticationError("bridge_enrollment_verifier_invalid")
    if record["status"] not in {"pending", "approved"}:
        raise AuthenticationError("bridge_enrollment_state_invalid")


def _enrollment_window(now: int | None, ttl_seconds: Any) -> tuple[int, int]:
    current = _now(now)
    ttl = int(ttl_seconds)
    if ttl < 60 or ttl > 900:
        raise ValueError("bridge_enrollment_ttl_invalid")
    return current, current + ttl


def _channel(value: str) -> str:
    channel = str(value or "").strip().lower()
    if channel not in BRIDGE_CHANNELS:
        raise ValueError("bridge_channel_unsupported")
    return channel


def _verifier_hash(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise ValueError("bridge_enrollment_verifier_hash_invalid")
    return normalized


def _user_code_hash(value: str) -> str:
    normalized = str(value or "").strip().upper().replace(" ", "")
    return _hash(normalized)


def _hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _required(value: str, error_code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(error_code)
    return normalized


def _now(value: int | None) -> int:
    return int(time.time() if value is None else value)
