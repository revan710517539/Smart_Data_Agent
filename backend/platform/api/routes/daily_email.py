from __future__ import annotations

from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import send_route_exception


def handle_daily_email_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_report_permission(context, "read")
        state = handler.services.daily_email_service.state(context.tenant_id, context.user_id)
        handler._send_json({"tenant_id": context.tenant_id, **state})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_daily_email_generate(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler.services.report_retention_service.enforce(context.tenant_id)
        handler._require_report_permission(context, "manage")
        run = handler.services.daily_email_service.generate(
            context.tenant_id,
            context.user_id,
            report_date=str(payload.get("report_date") or "").strip() or None,
            source_report_version_id=str(payload.get("source_report_version_id") or "").strip() or None,
        )
        handler._write_audit(
            context,
            "daily_email.generate",
            "daily_report_run",
            run["daily_report_run_id"],
            {
                "body_artifact_id": run["body_artifact_id"],
                "content_hash": run["content_hash"],
                "source_report_version_id": run["source_report_version_id"],
            },
        )
        handler._send_json({"tenant_id": context.tenant_id, "run": run}, HTTPStatus.CREATED)
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_daily_email_send(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_report_permission(context, "manage")
        handler._require_notification_permission(context, "create")
        run_id = str(payload.get("daily_report_run_id") or "").strip()
        run = handler.services.daily_email_service.send(context.tenant_id, context.user_id, run_id)
        handler._write_audit(
            context,
            "daily_email.enqueue",
            "daily_report_run",
            run_id,
            {"outbox_event_id": run.get("outbox_event_id"), "status": run["status"]},
        )
        handler._send_json({"tenant_id": context.tenant_id, "run": run}, HTTPStatus.ACCEPTED)
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)
