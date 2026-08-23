from __future__ import annotations

from typing import Any

from backend.platform.kernel.models import Capability
from backend.platform.kernel.store import capability_fingerprint


def register_runtime_jobs(automation_runtime: Any, kernel: Any) -> None:
    if "learning.observe_episode" not in set(automation_runtime.list_handlers()):
        automation_runtime.register_handler("learning.observe_episode", _observe_handler(kernel))
    if "learning.draft" not in set(automation_runtime.list_handlers()):
        automation_runtime.register_handler("learning.draft", _draft_handler(kernel))
    if "capability.promote" not in set(automation_runtime.list_handlers()):
        automation_runtime.register_handler("capability.promote", _promote_handler(kernel))
    if "eval.score" not in set(automation_runtime.list_handlers()):
        automation_runtime.register_handler("eval.score", _eval_handler(kernel))
    if "delivery.fulfill" not in set(automation_runtime.list_handlers()):
        automation_runtime.register_handler("delivery.fulfill", _delivery_handler(kernel))
    if "delivery.sync" not in set(automation_runtime.list_handlers()):
        automation_runtime.register_handler("delivery.sync", _delivery_sync_handler(kernel))


def ensure_runtime_learning_tasks(
    automation_runtime: Any,
    tenant_ids: list[str],
    owner_user_id: str,
) -> None:
    definitions = (
        (
            "system.runtime.learning.observe",
            "运行时分析观察",
            "learning.observe_episode",
            120,
        ),
        (
            "system.runtime.learning.draft",
            "运行时能力候选提炼",
            "learning.draft",
            300,
        ),
    )
    for tenant_id in dict.fromkeys(str(item) for item in tenant_ids if str(item).strip()):
        for task_code, task_name, handler_ref, timeout_seconds in definitions:
            if automation_runtime.store.get_task_by_code(tenant_id, task_code) is not None:
                continue
            automation_runtime.create_task(
                tenant_id,
                {
                    "task_code": task_code,
                    "task_name": task_name,
                    "task_type": "custom",
                    "trigger_type": "manual",
                    "handler_ref": handler_ref,
                    "task_config": {"source": "runtime.episode.completed", "activation": "candidate_only"},
                    "retry_policy": {"max_attempts": 3, "base_delay_seconds": 30},
                    "timeout_seconds": timeout_seconds,
                    "max_concurrency": 1,
                },
                owner_user_id,
            )


def _observe_handler(kernel: Any):
    def handler(tenant_id: str, config: dict, trigger_payload: dict, context: dict) -> dict:
        del config
        user_id = str(context.get("actor_user_id") or trigger_payload.get("user_id") or "")
        learning = kernel.learning_service
        if learning is None:
            return {"observed": False}
        event = {
            "tenant_id": tenant_id,
            "actor_user_id": user_id,
            "action": str(trigger_payload.get("action") or "application.runtime.episode"),
            "target_type": str(trigger_payload.get("target_type") or "episode"),
            "target_id": str(trigger_payload.get("episode_id") or ""),
            "event_id": str(trigger_payload.get("event_id") or ""),
        }
        return learning.observe_operation(event)

    return handler


def _draft_handler(kernel: Any):
    def handler(tenant_id: str, config: dict, trigger_payload: dict, context: dict) -> dict:
        user_id = str(context.get("actor_user_id") or trigger_payload.get("user_id") or "")
        payload = {**config, **trigger_payload, "tenant_id": tenant_id, "user_id": user_id}
        drafted = kernel.draft_provider.draft(payload) if getattr(kernel, "draft_provider", None) is not None else {}
        trigger = drafted.get("trigger") if isinstance(drafted.get("trigger"), dict) else (
            trigger_payload.get("trigger") if isinstance(trigger_payload.get("trigger"), dict) else {}
        )
        body = drafted.get("body") if isinstance(drafted.get("body"), dict) else (
            trigger_payload.get("body") if isinstance(trigger_payload.get("body"), dict) else {}
        )
        capability_id = str(drafted.get("capability_id") or trigger_payload.get("capability_id") or "learned.procedure")
        stored = kernel.store.upsert(
            user_id,
            Capability(
                capability_id=capability_id,
                kind="procedure",
                runtime_type="procedure",
                tenant_id=tenant_id,
                owner_scope="user",
                owner_id=user_id,
                title=str(drafted.get("title") or capability_id),
                description=str(drafted.get("description") or ""),
                status="candidate",
                trigger=trigger,
                body=body,
                fingerprint=capability_fingerprint({"kind": "procedure", "trigger": trigger, "body": body}),
                created_by=user_id,
            ),
        )
        return {
            "capability_id": stored.capability_id,
            "status": stored.status,
            "owner_id": stored.owner_id,
            "provider": drafted.get("provider") or "local_distiller",
            "fallback_from": drafted.get("fallback_from"),
        }

    return handler


def _promote_handler(kernel: Any):
    def handler(tenant_id: str, config: dict, trigger_payload: dict, context: dict) -> dict:
        min_accounts = int(trigger_payload.get("min_accounts") or config.get("min_accounts") or 3)
        return kernel.promote(tenant_id, str(context.get("actor_user_id") or ""), min_accounts=min_accounts)

    return handler


def _eval_handler(kernel: Any):
    def handler(tenant_id: str, config: dict, trigger_payload: dict, context: dict) -> dict:
        del config, context
        record = kernel.store.record_eval(
            {
                "tenant_id": tenant_id,
                "capability_id": trigger_payload.get("capability_id") or "",
                "metric": trigger_payload.get("metric") or "custom",
                "score": trigger_payload.get("score"),
                "detail": trigger_payload.get("detail") or {},
            }
        )
        return record

    return handler


def _delivery_handler(kernel: Any):
    def handler(tenant_id: str, config: dict, trigger_payload: dict, context: dict) -> dict:
        from backend.platform.api.routes.analysis import run_analysis

        services = getattr(kernel, "platform_services", None)
        if services is None:
            raise RuntimeError("automation_platform_services_not_bound")
        user_id = str(config.get("owner_user_id") or context.get("actor_user_id") or "")
        question = str(trigger_payload.get("question") or config.get("question") or "定时经营分析").strip()
        payload = run_analysis(
            services,
            user_id=user_id,
            tenant_id=tenant_id,
            question=question,
            page_context={
                "analysis_trigger": "delivery.fulfill",
                "capability_id": str(config.get("capability_id") or ""),
                "dataset_id": str(config.get("dataset_id") or ""),
            },
            cancellation_check=context.get("is_cancelled"),
        )
        return {
            "task_id": payload.get("task_id"),
            "status": payload.get("status"),
            "pack_snapshot_id": payload.get("pack_snapshot_id"),
        }

    return handler


def _delivery_sync_handler(kernel: Any):
    def handler(tenant_id: str, config: dict, trigger_payload: dict, context: dict) -> dict:
        from backend.platform.kernel.delivery import sync_delivery_contracts

        user_id = str(trigger_payload.get("user_id") or config.get("user_id") or context.get("actor_user_id") or "")
        procedures = kernel.store.list_visible(tenant_id, user_id, statuses=("active",))
        return sync_delivery_contracts(kernel.automation_runtime, tenant_id, user_id, procedures)

    return handler
