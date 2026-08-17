from __future__ import annotations

import hashlib
import json
import sqlite3
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.platform.storage import connect_sqlite


def approval_input_hash(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class InMemoryCapabilityApprovalStore:
    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def close(self) -> None:
        return None

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
        self._items[item["approval_id"]] = item
        return deepcopy(item)

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
        item = self._items.get(approval_id)
        if not item or item["tenant_id"] != tenant_id:
            raise KeyError("capability_approval_not_found")
        _validate_review(item, reviewer_user_id, decision)
        now = _utc_now()
        item.update(
            status="approved" if decision == "approved" else "rejected",
            reviewed_by=reviewer_user_id,
            reviewed_at=now,
            expires_at=(datetime.now(timezone.utc) + timedelta(seconds=_bounded_ttl(ttl_seconds))).isoformat()
            if decision == "approved"
            else None,
            review_comment=str(comments or "")[:2000],
        )
        return deepcopy(item)

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
        item = self._items.get(approval_id)
        if not item:
            raise PermissionError("capability_approval_invalid")
        _validate_consumption(item, tenant_id, requested_by, subject_type, subject_id, action, input_hash)
        item["status"] = "consumed"
        item["consumed_at"] = _utc_now()
        return deepcopy(item)

    def list(self, tenant_id: str, status: str | None = None) -> list[dict[str, Any]]:
        return [
            deepcopy(item)
            for item in sorted(self._items.values(), key=lambda value: value["requested_at"], reverse=True)
            if item["tenant_id"] == tenant_id and (not status or item["status"] == status)
        ]


class SQLiteCapabilityApprovalStore:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = connect_sqlite(db_path)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

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
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_capability_approvals(
                    approval_id, tenant_id, subject_type, subject_id, action,
                    input_hash, reason, requested_by, requested_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    item["approval_id"], tenant_id, subject_type, subject_id, action,
                    input_hash, item["reason"], requested_by, item["requested_at"],
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
        with self._conn:
            row = self._conn.execute(
                "SELECT * FROM platform_capability_approvals WHERE approval_id = ? AND tenant_id = ?",
                (approval_id, tenant_id),
            ).fetchone()
            if row is None:
                raise KeyError("capability_approval_not_found")
            item = dict(row)
            _validate_review(item, reviewer_user_id, decision)
            now = _utc_now()
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=_bounded_ttl(ttl_seconds))
            ).isoformat() if decision == "approved" else None
            cursor = self._conn.execute(
                """
                UPDATE platform_capability_approvals
                SET status = ?, reviewed_by = ?, reviewed_at = ?, expires_at = ?, review_comment = ?
                WHERE approval_id = ? AND tenant_id = ? AND status = 'pending'
                """,
                (
                    "approved" if decision == "approved" else "rejected",
                    reviewer_user_id,
                    now,
                    expires_at,
                    str(comments or "")[:2000],
                    approval_id,
                    tenant_id,
                ),
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
        with self._conn:
            row = self._conn.execute(
                "SELECT * FROM platform_capability_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                raise PermissionError("capability_approval_invalid")
            item = dict(row)
            _validate_consumption(item, tenant_id, requested_by, subject_type, subject_id, action, input_hash)
            consumed_at = _utc_now()
            cursor = self._conn.execute(
                """
                UPDATE platform_capability_approvals
                SET status = 'consumed', consumed_at = ?
                WHERE approval_id = ? AND status = 'approved'
                """,
                (consumed_at, approval_id),
            )
            if cursor.rowcount != 1:
                raise PermissionError("capability_approval_already_consumed")
        return self.get(tenant_id, approval_id)

    def get(self, tenant_id: str, approval_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM platform_capability_approvals WHERE approval_id = ? AND tenant_id = ?",
            (approval_id, tenant_id),
        ).fetchone()
        if row is None:
            raise KeyError("capability_approval_not_found")
        return dict(row)

    def list(self, tenant_id: str, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM platform_capability_approvals WHERE tenant_id = ? AND status = ? ORDER BY requested_at DESC LIMIT 200",
                (tenant_id, status),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM platform_capability_approvals WHERE tenant_id = ? ORDER BY requested_at DESC LIMIT 200",
                (tenant_id,),
            ).fetchall()
        return [dict(row) for row in rows]


def _new_request(
    tenant_id: str,
    subject_type: str,
    subject_id: str,
    action: str,
    input_hash: str,
    requested_by: str,
    reason: str,
) -> dict[str, Any]:
    if subject_type not in {"skill", "mcp"}:
        raise ValueError("invalid_capability_approval_subject_type")
    if not subject_id or not action or not requested_by:
        raise ValueError("capability_approval_subject_action_and_requester_required")
    if len(input_hash) != 64 or any(char not in "0123456789abcdef" for char in input_hash.lower()):
        raise ValueError("capability_approval_input_hash_invalid")
    return {
        "approval_id": f"approval_{uuid4().hex}",
        "tenant_id": tenant_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "action": action,
        "input_hash": input_hash.lower(),
        "reason": str(reason or "")[:2000],
        "requested_by": requested_by,
        "requested_at": _utc_now(),
        "status": "pending",
        "reviewed_by": None,
        "reviewed_at": None,
        "expires_at": None,
        "consumed_at": None,
        "review_comment": "",
    }


def _validate_review(item: dict[str, Any], reviewer_user_id: str, decision: str) -> None:
    if decision not in {"approved", "rejected"}:
        raise ValueError("invalid_capability_approval_decision")
    if item.get("status") != "pending":
        raise RuntimeError("capability_approval_not_pending")
    if not reviewer_user_id or item.get("requested_by") == reviewer_user_id:
        raise PermissionError("capability_approval_four_eyes_required")


def _validate_consumption(
    item: dict[str, Any],
    tenant_id: str,
    requested_by: str,
    subject_type: str,
    subject_id: str,
    action: str,
    input_hash: str,
) -> None:
    if item.get("status") != "approved":
        raise PermissionError("capability_approval_not_approved")
    if item.get("tenant_id") != tenant_id or item.get("requested_by") != requested_by:
        raise PermissionError("capability_approval_context_mismatch")
    if (
        item.get("subject_type") != subject_type
        or item.get("subject_id") != subject_id
        or item.get("action") != action
        or item.get("input_hash") != input_hash.lower()
    ):
        raise PermissionError("capability_approval_scope_mismatch")
    expires_at = datetime.fromisoformat(str(item.get("expires_at") or "").replace("Z", "+00:00"))
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    else:
        expires_at = expires_at.astimezone(timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise PermissionError("capability_approval_expired")


def _bounded_ttl(value: int) -> int:
    return max(60, min(int(value or 900), 3600))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
