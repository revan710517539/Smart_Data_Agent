from __future__ import annotations

import hashlib
import json
from threading import RLock
from typing import Any

from backend.platform.kernel.isolation import assert_account_write, is_visible_to, normalize_scope
from backend.platform.kernel.models import Capability, CapabilityStatus, new_id, utc_now


def capability_fingerprint(payload: dict[str, Any]) -> str:
    material = {
        "kind": payload.get("kind"),
        "trigger": payload.get("trigger") or {},
        "steps": (payload.get("body") or {}).get("steps") if isinstance(payload.get("body"), dict) else [],
        "dataset_id": (payload.get("trigger") or {}).get("dataset_id"),
        "intent_rule_id": (payload.get("trigger") or {}).get("intent_rule_id"),
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class InMemoryAccountCapabilityStore:
    """Account-keyed capability store. User rows are never listed across accounts."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._items: dict[tuple[str, str, str, str], Capability] = {}
        self._episodes: dict[str, dict[str, Any]] = {}
        self._packs: dict[str, dict[str, Any]] = {}
        self._evals: list[dict[str, Any]] = []

    def close(self) -> None:
        return None

    def upsert(self, actor_user_id: str, capability: Capability) -> Capability:
        assert_account_write(capability.tenant_id, actor_user_id, capability)
        fingerprint = capability.fingerprint or capability_fingerprint(
            {"kind": capability.kind, "trigger": capability.trigger, "body": capability.body}
        )
        stored = Capability(
            capability_id=capability.capability_id,
            kind=capability.kind,
            runtime_type=capability.runtime_type,
            tenant_id=capability.tenant_id,
            owner_scope=normalize_scope(capability.owner_scope),
            owner_id=capability.owner_id,
            title=capability.title,
            description=capability.description,
            version=capability.version,
            status=capability.status,
            trigger=dict(capability.trigger),
            body=dict(capability.body),
            fingerprint=fingerprint,
            permission_scope=tuple(capability.permission_scope),
            created_by=capability.created_by or actor_user_id,
        )
        key = (stored.tenant_id, stored.owner_scope, stored.owner_id, stored.capability_id)
        with self._lock:
            self._items[key] = stored
        return stored

    def get(
        self,
        tenant_id: str,
        owner_scope: str,
        owner_id: str,
        capability_id: str,
    ) -> Capability | None:
        with self._lock:
            return self._items.get((tenant_id, normalize_scope(owner_scope), owner_id, capability_id))

    def list_visible(
        self,
        tenant_id: str,
        user_id: str,
        *,
        statuses: tuple[str, ...] = ("active",),
        role_ids: tuple[str, ...] = (),
        org_ids: tuple[str, ...] = (),
    ) -> list[Capability]:
        allowed = set(statuses)
        with self._lock:
            items = list(self._items.values())
        return [
            item
            for item in items
            if is_visible_to(item, tenant_id, user_id, role_ids=role_ids, org_ids=org_ids) and item.status in allowed
        ]

    def list_user_active(self, tenant_id: str, *, status: CapabilityStatus = "active") -> list[Capability]:
        with self._lock:
            items = list(self._items.values())
        return [
            item
            for item in items
            if item.tenant_id == tenant_id and item.owner_scope == "user" and item.status == status
        ]

    def save_episode(self, episode: dict[str, Any]) -> dict[str, Any]:
        record = dict(episode)
        record.setdefault("episode_id", new_id("ep"))
        record.setdefault("created_at", utc_now())
        with self._lock:
            self._episodes[str(record["episode_id"])] = record
        return dict(record)

    def save_pack(self, pack: dict[str, Any]) -> dict[str, Any]:
        record = dict(pack)
        record.setdefault("created_at", utc_now())
        with self._lock:
            self._packs[str(record["snapshot_id"])] = record
        return dict(record)

    def get_pack(self, tenant_id: str, user_id: str, snapshot_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._packs.get(snapshot_id)
        if record is None:
            return None
        if record.get("tenant_id") != tenant_id or record.get("user_id") != user_id:
            raise PermissionError("capability_pack_account_isolation")
        return dict(record)

    def get_episode(self, tenant_id: str, user_id: str, episode_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._episodes.get(episode_id)
        if item is None:
            return None
        if item.get("tenant_id") != tenant_id or item.get("user_id") != user_id:
            raise PermissionError("episode_account_isolation")
        return dict(item)

    def record_eval(self, payload: dict[str, Any]) -> dict[str, Any]:
        record = dict(payload)
        record.setdefault("eval_id", new_id("eval"))
        record.setdefault("created_at", utc_now())
        with self._lock:
            self._evals.append(record)
        return dict(record)

    def list_evals(self, tenant_id: str, capability_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._evals)
        return [
            dict(item)
            for item in items
            if item.get("tenant_id") == tenant_id
            and (not capability_id or item.get("capability_id") == capability_id)
        ]
