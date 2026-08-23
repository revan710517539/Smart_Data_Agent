from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.platform.kernel.models import Capability
from backend.platform.kernel.store import capability_fingerprint


DEFAULT_MIN_ACCOUNTS = 3


def promote_common_capabilities(
    store: Any,
    tenant_id: str,
    actor_user_id: str,
    *,
    min_accounts: int = DEFAULT_MIN_ACCOUNTS,
) -> dict[str, Any]:
    """Lift repeated personal procedures to a tenant candidate. Bodies stay fingerprints only."""

    grouped: dict[str, list[Capability]] = defaultdict(list)
    for item in store.list_user_active(tenant_id, status="active"):
        if item.kind != "procedure":
            continue
        grouped[item.fingerprint or capability_fingerprint({"kind": item.kind, "trigger": item.trigger, "body": item.body})].append(item)
    promoted: list[str] = []
    skipped = 0
    for fingerprint, items in grouped.items():
        owners = {item.owner_id for item in items if item.owner_id}
        if len(owners) < max(2, int(min_accounts)):
            skipped += 1
            continue
        sample = items[0]
        common_id = f"common.{fingerprint[:12]}"
        existing = store.get(tenant_id, "tenant", tenant_id, common_id)
        if existing is not None:
            skipped += 1
            continue
        store.upsert(
            actor_user_id,
            Capability(
                capability_id=common_id,
                kind="procedure",
                runtime_type="procedure",
                tenant_id=tenant_id,
                owner_scope="tenant",
                owner_id=tenant_id,
                title=sample.title or common_id,
                description="Abstracted shared procedure. Source account ids are not stored.",
                status="review",
                trigger={
                    "dataset_id": (sample.trigger or {}).get("dataset_id"),
                    "intent_rule_id": (sample.trigger or {}).get("intent_rule_id"),
                    "source_account_count": len(owners),
                },
                body={"steps": (sample.body or {}).get("steps") or [], "source_account_count": len(owners)},
                fingerprint=fingerprint,
                created_by=actor_user_id,
            ),
        )
        promoted.append(common_id)
    return {
        "tenant_id": tenant_id,
        "promoted": promoted,
        "skipped_groups": skipped,
        "min_accounts": max(2, int(min_accounts)),
    }
