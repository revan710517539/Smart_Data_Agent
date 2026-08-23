from __future__ import annotations

from typing import Any

from backend.platform.kernel.models import Capability, CapabilityScope

USER_SCOPES = frozenset({"user"})
SHARED_SCOPES = frozenset({"role", "org", "tenant", "platform"})
ALLOWED_SCOPES = USER_SCOPES | SHARED_SCOPES


def normalize_scope(value: str) -> CapabilityScope:
    scope = str(value or "").strip().lower()
    if scope not in ALLOWED_SCOPES:
        raise ValueError(f"unsupported_capability_scope:{value}")
    return scope  # type: ignore[return-value]


def assert_account_write(tenant_id: str, actor_user_id: str, capability: Capability) -> None:
    if capability.tenant_id != tenant_id:
        raise PermissionError("capability_tenant_mismatch")
    if capability.owner_scope == "user" and capability.owner_id != actor_user_id:
        raise PermissionError("capability_account_isolation")


def is_visible_to(
    capability: Capability,
    tenant_id: str,
    user_id: str,
    *,
    role_ids: tuple[str, ...] = (),
    org_ids: tuple[str, ...] = (),
) -> bool:
    if capability.tenant_id != tenant_id:
        return False
    if capability.status not in {"active", "review", "candidate"}:
        return False
    if capability.owner_scope == "user":
        return capability.owner_id == user_id
    if capability.owner_scope == "role":
        return capability.owner_id in set(role_ids)
    if capability.owner_scope == "org":
        return capability.owner_id in set(org_ids)
    if capability.owner_scope == "tenant":
        return capability.owner_id == tenant_id
    if capability.owner_scope == "platform":
        return capability.owner_id in {"platform", "global"}
    return False


def merge_pack_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """User entries override tenant/platform entries with the same capability_id."""

    rank = {"user": 4, "role": 3, "org": 2, "tenant": 1, "platform": 0}
    chosen: dict[str, dict[str, Any]] = {}
    for item in entries:
        key = str(item.get("capability_id") or "")
        if not key:
            continue
        current = chosen.get(key)
        if current is None or rank.get(str(item.get("owner_scope")), 0) >= rank.get(str(current.get("owner_scope")), 0):
            chosen[key] = item
    return list(chosen.values())
