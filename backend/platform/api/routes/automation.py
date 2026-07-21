from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs
from uuid import uuid4

from backend.platform.api.support import MAX_JSON_BODY_BYTES, RequestBodyTooLarge, send_route_exception


def handle_automation_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_automation_permission(context, "read")
        tasks = handler.services.automation_store.list_tasks(context.tenant_id)
        runs = handler.services.automation_store.list_runs(context.tenant_id)
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                "handlers": handler.services.automation_runtime.list_handlers(),
                "tasks": tasks,
                "runs": runs,
                "count": {"tasks": len(tasks), "runs": len(runs)},
            }
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_automation_task_create(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_automation_permission(context, "create")
        task = handler.services.automation_runtime.create_task(context.tenant_id, payload, context.user_id)
        handler._write_audit(
            context,
            "automation.task.create",
            "automation_task",
            task["automation_task_id"],
            {"handler_ref": task["handler_ref"], "trigger_type": task["trigger_type"]},
        )
        handler._send_json({"tenant_id": context.tenant_id, "task": task})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_automation_task_update(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_automation_permission(context, "create")
        task_id = str(payload.get("automation_task_id") or "").strip()
        if not task_id or payload.get("expected_lock_version") is None:
            raise ValueError("automation_task_id_and_expected_lock_version_required")
        task = handler.services.automation_runtime.update_task(
            context.tenant_id,
            task_id,
            payload,
            context.user_id,
            int(payload["expected_lock_version"]),
        )
        handler._write_audit(
            context,
            "automation.task.update",
            "automation_task",
            task_id,
            {"status": task["status"], "lock_version": task["lock_version"]},
        )
        handler._send_json({"tenant_id": context.tenant_id, "task": task})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_automation_run_create(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_automation_permission(context, "create")
        task_id = str(payload.get("automation_task_id") or "").strip()
        trigger_payload = payload.get("trigger_payload", {})
        if not isinstance(trigger_payload, dict):
            raise ValueError("trigger_payload_must_be_object")
        idempotency_key = str(handler.headers.get("Idempotency-Key") or payload.get("idempotency_key") or f"manual-{uuid4().hex}")
        run = handler.services.automation_runtime.trigger(
            context.tenant_id,
            task_id,
            context.user_id,
            idempotency_key,
            trigger_payload,
        )
        handler._write_audit(
            context,
            "automation.run.enqueue",
            "automation_run",
            run["automation_run_id"],
            {"task_id": task_id, "status": run["status"]},
        )
        handler._send_json({"tenant_id": context.tenant_id, "run": run})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_automation_run_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_automation_permission(context, "read")
        run_id = str((params.get("run_id") or [""])[0]).strip()
        run = handler.services.automation_store.get_run(context.tenant_id, run_id)
        if str(run.get("created_by")) != context.user_id:
            raise PermissionError("Automation run is unavailable.")
        handler._send_json({"tenant_id": context.tenant_id, "run": run})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_automation_run_cancel(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_automation_permission(context, "create")
        run_id = str(payload.get("automation_run_id") or "").strip()
        run = handler.services.automation_store.cancel_run(context.tenant_id, run_id, context.user_id)
        handler._write_audit(
            context,
            "automation.run.cancel",
            "automation_run",
            run_id,
            {"status": run["status"]},
        )
        handler._send_json({"tenant_id": context.tenant_id, "run": run})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_subscriptions_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_notification_permission(context, "read")
        subscriptions = handler.services.automation_store.list_subscriptions(context.tenant_id, context.user_id)
        deliveries = handler.services.automation_store.list_in_app_deliveries(context.tenant_id, context.user_id)
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                "subscriptions": subscriptions,
                "in_app_deliveries": deliveries,
                "count": {"subscriptions": len(subscriptions), "in_app_deliveries": len(deliveries)},
            }
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_subscription_create(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_notification_permission(context, "create")
        subscription = handler.services.automation_store.create_subscription(
            context.tenant_id,
            payload,
            context.user_id,
        )
        handler._write_audit(
            context,
            "notification.subscription.create",
            "subscription",
            subscription["subscription_id"],
            {"event_types": subscription["event_types"], "channel_type": subscription["channel_type"]},
        )
        handler._send_json({"tenant_id": context.tenant_id, "subscription": subscription})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_subscription_update(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_notification_permission(context, "create")
        subscription_id = str(payload.get("subscription_id") or "").strip()
        if not subscription_id or payload.get("expected_lock_version") is None:
            raise ValueError("subscription_id_and_expected_lock_version_required")
        subscription = handler.services.automation_store.update_subscription(
            context.tenant_id,
            subscription_id,
            payload,
            context.user_id,
            int(payload["expected_lock_version"]),
        )
        handler._write_audit(
            context,
            "notification.subscription.update",
            "subscription",
            subscription_id,
            {"status": subscription["status"], "lock_version": subscription["lock_version"]},
        )
        handler._send_json({"tenant_id": context.tenant_id, "subscription": subscription})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_subscription_delete(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_notification_permission(context, "create")
        subscription_id = str((params.get("subscription_id") or [""])[0]).strip()
        lock_text = str((params.get("expected_lock_version") or [""])[0]).strip()
        if not subscription_id or not lock_text:
            raise ValueError("subscription_id_and_expected_lock_version_required")
        subscription = handler.services.automation_store.disable_subscription(
            context.tenant_id,
            subscription_id,
            context.user_id,
            int(lock_text),
        )
        handler._write_audit(
            context,
            "notification.subscription.disable",
            "subscription",
            subscription_id,
            {"lock_version": subscription["lock_version"]},
        )
        handler._send_json({"tenant_id": context.tenant_id, "subscription": subscription})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_notification_provider_callback(handler: Any) -> None:
    """Receive an HMAC-authenticated provider receipt without a user session."""
    try:
        content_length = int(handler.headers.get("content-length") or "0")
        if content_length <= 0 or content_length > MAX_JSON_BODY_BYTES:
            raise RequestBodyTooLarge("provider_callback_body_invalid")
        raw = handler.rfile.read(content_length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("provider_callback_body_must_be_object")
        provider = str(payload.get("provider") or "").strip().lower()
        tenant_id = str(payload.get("tenant_id") or "").strip()
        provider_event_id = str(payload.get("provider_event_id") or "").strip()
        provider_message_id = str(payload.get("provider_message_id") or "").strip()
        event_type = str(payload.get("event_type") or "").strip().lower()
        if not provider or not tenant_id or not provider_event_id or not provider_message_id or not event_type:
            raise ValueError("provider_callback_required_fields_missing")
        env_suffix = re.sub(r"[^A-Z0-9]", "_", provider.upper())
        secret = (
            os.getenv(f"SMART_DATA_AGENT_PROVIDER_CALLBACK_SECRET_{env_suffix}", "").strip()
            or os.getenv("SMART_DATA_AGENT_PROVIDER_CALLBACK_SECRET", "").strip()
        )
        if not secret:
            handler._send_json(
                {"error": "provider_callback_not_configured"},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        supplied = str(handler.headers.get("X-Provider-Signature") or "").strip().lower()
        if supplied.startswith("sha256="):
            supplied = supplied.removeprefix("sha256=")
        expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            handler._send_json({"error": "provider_callback_signature_invalid"}, HTTPStatus.UNAUTHORIZED)
            return
        payload_hash = hashlib.sha256(raw).hexdigest()
        callback = handler.services.automation_store.record_provider_callback(
            tenant_id,
            provider=provider,
            provider_event_id=provider_event_id,
            provider_message_id=provider_message_id,
            event_type=event_type,
            payload_hash=payload_hash,
            safe_payload={
                "occurred_at": str(payload.get("occurred_at") or "")[:64],
                "reason_code": str(payload.get("reason_code") or "")[:100],
            },
        )
        handler._send_json(
            {
                "callback_id": callback["callback_id"],
                "processing_status": callback["processing_status"],
            },
            HTTPStatus.ACCEPTED,
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)
