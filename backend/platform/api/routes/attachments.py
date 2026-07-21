from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import first_query_value, send_route_exception


def handle_report_image_upload(handler: Any) -> None:
    try:
        payload = handler._read_json(max_bytes=8 * 1024 * 1024)
        context = handler._request_context(payload=payload)
        handler._require_report_permission(context, "create")
        result = handler.services.knowledge_service.upload_report_image(
            context.tenant_id, payload, context.user_id
        )
        attachment = result.get("attachment") if isinstance(result.get("attachment"), dict) else {}
        artifact = result.get("artifact") if isinstance(result.get("artifact"), dict) else {}
        handler._write_audit(
            context,
            "report.image.upload",
            "file_attachment",
            str(attachment.get("attachment_id") or ""),
            {
                "artifact_id": artifact.get("artifact_id"),
                "content_hash": artifact.get("content_hash"),
                "size_bytes": artifact.get("size_bytes"),
                "scan_status": result.get("scan", {}).get("status")
                if isinstance(result.get("scan"), dict)
                else "",
            },
        )
        handler._send_json({"tenant_id": context.tenant_id, **result})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_attachment_content_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_report_permission(context, "read")
        attachment_id = first_query_value(params, "attachment_id") or ""
        if not attachment_id:
            raise ValueError("attachment_id_required")
        metadata, content = handler.services.knowledge_service.get_report_image_content(
            context.tenant_id, attachment_id
        )
        attachment = metadata["attachment"]
        artifact = metadata["artifact"]
        safe_name = str(attachment.get("file_name") or attachment_id).replace('"', "")
        handler._send_bytes(
            content,
            content_type=str(artifact.get("content_type") or "application/octet-stream"),
            headers={
                "Content-Disposition": f'inline; filename="{safe_name}"',
                "ETag": f'"{artifact.get("content_hash")}"',
            },
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)
