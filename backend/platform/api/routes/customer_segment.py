from __future__ import annotations

from typing import Any

from backend.platform.api.support import send_route_exception
from backend.platform.customer_segment import confirm_customer_list, preview_customer_list


def handle_customer_segment_list_preview(handler: Any) -> None:
    try:
        payload = handler._read_json(max_bytes=12 * 1024 * 1024)
        context = handler._request_context(payload=payload)
        handler._require_application_permission(context, "execute")
        result = preview_customer_list(
            str(payload.get("file_name") or payload.get("fileName") or ""),
            str(payload.get("content_base64") or payload.get("contentBase64") or ""),
        )
        handler._send_json({"tenant_id": context.tenant_id, "preview": result})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_customer_segment_list_confirm(handler: Any) -> None:
    try:
        payload = handler._read_json(max_bytes=12 * 1024 * 1024)
        context = handler._request_context(payload=payload)
        handler._require_application_permission(context, "execute")
        result = confirm_customer_list(
            handler.services,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            file_name=str(payload.get("file_name") or payload.get("fileName") or ""),
            content_base64=str(payload.get("content_base64") or payload.get("contentBase64") or ""),
            expected_content_hash=str(payload.get("expected_content_hash") or payload.get("expectedContentHash") or ""),
        )
        handler._write_audit(
            context,
            "customer_segment.list.confirm",
            "customer_segment_list",
            target_id=str(result["customer_list"].get("artifactId") or ""),
            detail={
                "file_name": result["customer_list"].get("fileName"),
                "customer_count": result["customer_list"].get("customerCount"),
                "duplicate_count": result["customer_list"].get("duplicateCount"),
                "content_hash": result["customer_list"].get("contentHash"),
            },
        )
        handler._send_json({"tenant_id": context.tenant_id, **result})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)
