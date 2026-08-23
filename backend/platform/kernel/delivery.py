from __future__ import annotations

import hashlib
from typing import Any

from backend.platform.kernel.models import Capability


def sync_delivery_contracts(
    automation_runtime: Any,
    tenant_id: str,
    user_id: str,
    procedures: list[Capability],
) -> dict[str, Any]:
    """Upsert per-account scheduled analysis jobs from active procedures."""

    ensured: list[str] = []
    skipped = 0
    if automation_runtime is None:
        return {"ensured": ensured, "skipped": skipped, "reason": "automation_runtime_missing"}
    for procedure in procedures:
        if procedure.owner_scope != "user" or procedure.owner_id != user_id:
            skipped += 1
            continue
        if procedure.status != "active" or procedure.kind != "procedure":
            skipped += 1
            continue
        schedule = str((procedure.trigger or {}).get("schedule") or "").strip()
        if not _looks_like_cron(schedule):
            skipped += 1
            continue
        task_code = _delivery_task_code(user_id, procedure.fingerprint or procedure.capability_id)
        existing = automation_runtime.store.get_task_by_code(tenant_id, task_code)
        payload = {
            "task_code": task_code,
            "task_name": f"准时分析 {procedure.title or procedure.capability_id}",
            "task_type": "analysis",
            "trigger_type": "schedule",
            "schedule_expression": schedule,
            "handler_ref": "delivery.fulfill",
            "timeout_seconds": 900,
            "max_concurrency": 1,
            "task_config": {
                "owner_user_id": user_id,
                "capability_id": procedure.capability_id,
                "dataset_id": (procedure.trigger or {}).get("dataset_id") or "",
                "question": (procedure.trigger or {}).get("question") or procedure.title or "定时经营分析",
            },
        }
        if existing is None:
            automation_runtime.create_task(tenant_id, payload, user_id)
        elif str(existing.get("schedule_expression") or "") != schedule or str(existing.get("status") or "") == "paused":
            automation_runtime.update_task(
                tenant_id,
                existing["automation_task_id"],
                {
                    "schedule_expression": schedule,
                    "status": "active",
                    "task_config": payload["task_config"],
                },
                user_id,
                int(existing.get("lock_version") or 1),
            )
        ensured.append(task_code)
    return {"ensured": ensured, "skipped": skipped}


def _delivery_task_code(user_id: str, fingerprint: str) -> str:
    digest = hashlib.sha256(f"{user_id}:{fingerprint}".encode("utf-8")).hexdigest()[:20]
    return f"system.delivery.{digest}"


def _looks_like_cron(value: str) -> bool:
    parts = [part for part in str(value or "").split() if part]
    return len(parts) == 5
