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
from backend.platform.integrations.teams import complete_device_authorization, send_markdown_to_self, start_device_authorization
from backend.platform.automation.metric_subscription import collect_metric_snapshot, normalize_teams_message_template, render_teams_metric_markdown
from backend.platform.metrics.defaults import teams_subscription_test_metrics


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


def handle_teams_metric_subscription_auth_start(handler: Any) -> None:
    """Start short-lived browser authorization without persisting an access token."""
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_notification_permission(context, "create")
        _metric_subscription_definition(handler, context, payload)
        handler._send_json({"authorization": start_device_authorization()})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_teams_metric_subscription_auth_poll(handler: Any) -> None:
    """Exchange an approved device code directly into encrypted subscription config."""
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_notification_permission(context, "create")
        definition = _metric_subscription_definition(handler, context, payload)
        device_code = str(payload.get("device_code") or "").strip()
        if not device_code:
            raise ValueError("teams_device_code_required")
        access_token = complete_device_authorization(device_code)
        if access_token is None:
            handler._send_json({"completed": False})
            return
        handler.services.automation_store.upsert_teams_connection(context.tenant_id, context.user_id, access_token)
        subscription, task = _enable_teams_metric_subscription(handler, context, definition, access_token)
        handler._send_json({"completed": True, "subscription": subscription, "automation_task": task})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_teams_connection_get(handler: Any, query: str) -> None:
    """Read a safe per-user connection state; an encrypted token is never returned."""
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_notification_permission(context, "read")
        connection = handler.services.automation_store.get_teams_connection(context.tenant_id, context.user_id)
        handler._send_json({"tenant_id": context.tenant_id, "connection": _teams_connection_view(connection)})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_teams_connection_auth_start(handler: Any) -> None:
    """Begin the user-owned Teams browser authorization before any rule is enabled."""
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_notification_permission(context, "create")
        handler._send_json({"authorization": start_device_authorization()})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_teams_connection_auth_poll(handler: Any) -> None:
    """Persist only a completed Teams self-message authorization for its owner."""
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_notification_permission(context, "create")
        device_code = str(payload.get("device_code") or "").strip()
        if not device_code:
            raise ValueError("teams_device_code_required")
        access_token = complete_device_authorization(device_code)
        if access_token is None:
            handler._send_json({"completed": False, "connection": {"connected": False, "provider": "360teams_self"}})
            return
        connection = handler.services.automation_store.upsert_teams_connection(context.tenant_id, context.user_id, access_token)
        handler._write_audit(
            context,
            "notification.teams_connection.upsert",
            "subscription",
            str(connection["subscription_id"]),
            {"provider": "360teams_self"},
        )
        handler._send_json({"completed": True, "connection": _teams_connection_view(connection)})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_teams_metric_subscription_enable(handler: Any) -> None:
    """Enable a metric rule only when this signed-in user already connected Teams."""
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_notification_permission(context, "create")
        definition = _metric_subscription_definition(handler, context, payload)
        connection = handler.services.automation_store.get_teams_connection(
            context.tenant_id,
            context.user_id,
            reveal_config=True,
        )
        access_token = str(dict(connection or {}).get("channel_config", {}).get("access_token") or "").strip()
        if not access_token:
            raise ValueError("teams_connection_required")
        subscription, task = _enable_teams_metric_subscription(handler, context, definition, access_token)
        handler._send_json({"tenant_id": context.tenant_id, "subscription": subscription, "automation_task": task})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_teams_metric_subscription_test(handler: Any) -> None:
    """Immediately send the user's current template to their already-connected Teams account.

    This never creates a subscription, task, delivery record or reusable test
    token; it is a deliberate, user-triggered connection check.
    """
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_notification_permission(context, "create")
        definition = _metric_subscription_definition(handler, context, payload)
        connection = handler.services.automation_store.get_teams_connection(
            context.tenant_id,
            context.user_id,
            reveal_config=True,
        )
        access_token = str(dict(connection or {}).get("channel_config", {}).get("access_token") or "").strip()
        if not access_token:
            raise ValueError("teams_connection_required")
        snapshots = [collect_metric_snapshot(handler.services, context.tenant_id, context.user_id, metric) for metric in definition["metrics"]]
        title, text = render_teams_metric_markdown({"snapshots": snapshots, "message_template": definition["message_template"]})
        provider_message_id = send_markdown_to_self(access_token, f"测试 · {title}"[:50], text)
        handler._write_audit(
            context,
            "notification.teams_metric_subscription.test",
            "teams_connection",
            str(dict(connection or {}).get("subscription_id") or context.user_id),
            {"metric_ids": [metric.get("metricId") for metric in definition["metrics"]], "provider": "360teams_self"},
        )
        handler._send_json({"tenant_id": context.tenant_id, "sent": True, "provider_message_id": provider_message_id})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def _enable_teams_metric_subscription(handler: Any, context: Any, definition: dict[str, Any], access_token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    task_identity = ":".join(
        (
            str(context.user_id),
            ",".join(str(metric.get("metricId") or "") for metric in definition["metrics"]),
            str(definition["schedule_expression"]),
            str(definition["schedule_timezone"]),
            json.dumps(definition["message_template"], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
    )
    task_code = "system.teams-metric." + hashlib.sha256(task_identity.encode("utf-8")).hexdigest()[:20]
    existing_task = handler.services.automation_store.get_task_by_code(context.tenant_id, task_code)
    if existing_task is not None:
        subscription_id = str(dict(existing_task.get("task_config") or {}).get("subscription_id") or "")
        return handler.services.automation_store.get_subscription(context.tenant_id, subscription_id), existing_task
    subscription = handler.services.automation_store.create_subscription(
        context.tenant_id,
        {
            "subscription_name": definition["subscription_name"],
            "event_types": ["metric.daily.snapshot.ready"],
            "channel_type": "webhook",
            "channel_config": {"provider": "360teams_self", "access_token": access_token},
        },
        context.user_id,
    )
    task = handler.services.automation_runtime.create_task(
        context.tenant_id,
        {
            "task_code": task_code,
            "task_name": f"每日指标订阅：{'、'.join(str(metric['metricName']) for metric in definition['metrics'])}",
            "task_type": "notification",
            "trigger_type": "schedule",
            "schedule_expression": definition["schedule_expression"],
            "handler_ref": "metric.subscription.snapshot",
            "task_config": {
                "subscription_id": subscription["subscription_id"],
                "metrics": definition["metrics"],
                "message_template": definition["message_template"],
                "schedule_timezone": definition["schedule_timezone"],
            },
            "retry_policy": {"max_attempts": 3, "base_delay_seconds": 60},
            "timeout_seconds": 120,
            "max_concurrency": 1,
        },
        context.user_id,
    )
    handler._write_audit(
        context,
        "notification.teams_metric_subscription.create",
        "subscription",
        subscription["subscription_id"],
        {"metric_ids": [metric.get("metricId") for metric in definition["metrics"]], "channel": "360teams_self", "task_id": task["automation_task_id"]},
    )
    return subscription, task


def _teams_connection_view(connection: dict[str, Any] | None) -> dict[str, Any]:
    if connection is None:
        return {"connected": False, "provider": "360teams_self"}
    return {"connected": True, "provider": str(connection.get("channel_provider") or "360teams_self")}


def _metric_subscription_definition(handler: Any, context: Any, payload: dict[str, Any]) -> dict[str, Any]:
    requested = payload.get("metric") if isinstance(payload.get("metric"), dict) else {}
    raw_metric_ids = payload.get("metric_ids") if isinstance(payload.get("metric_ids"), list) else payload.get("metricIds")
    metric_ids = [str(item).strip() for item in raw_metric_ids] if isinstance(raw_metric_ids, list) else []
    legacy_metric_id = str(requested.get("metricId") or payload.get("metric_id") or "").strip()
    if legacy_metric_id and legacy_metric_id not in metric_ids:
        metric_ids.append(legacy_metric_id)
    metric_ids = list(dict.fromkeys(metric_id for metric_id in metric_ids if metric_id))
    if not metric_ids:
        raise ValueError("metric_subscription_metric_required")
    if len(metric_ids) > 12:
        raise ValueError("metric_subscription_metric_limit_exceeded")
    handler._require_metric_permission(context, "read")
    metrics: list[dict[str, Any]] = []
    test_metrics = {str(metric["metricId"]): metric for metric in teams_subscription_test_metrics()}
    for metric_id in metric_ids:
        metric = test_metrics.get(metric_id) or handler.services.metric_dictionary_store.get(context.tenant_id, metric_id)
        if not isinstance(metric, dict):
            raise ValueError("metric_subscription_metric_not_found")
        if any(not str(metric.get(field) or "").strip() for field in ("metricName", "metricCode", "datasetId")):
            raise ValueError("metric_subscription_metric_execution_metadata_required")
        metrics.append(metric)
    subscription_name = str(payload.get("subscription_name") or payload.get("subscriptionName") or f"{metrics[0]['metricName']} 等指标每日快报").strip()
    if not subscription_name or len(subscription_name) > 300:
        raise ValueError("invalid_subscription_name")
    return {
        "metrics": metrics,
        "subscription_name": subscription_name,
        "schedule_expression": str(payload.get("schedule_expression") or payload.get("scheduleExpression") or "0 9 * * *").strip(),
        "schedule_timezone": str(payload.get("schedule_timezone") or payload.get("scheduleTimezone") or "Asia/Shanghai").strip(),
        "message_template": normalize_teams_message_template(payload.get("message_template") or payload.get("messageTemplate"), metric_ids),
    }


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
