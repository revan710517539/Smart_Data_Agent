from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, quote

from backend.platform.api.support import first_query_value, send_route_exception


def handle_message_board_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_message_board_permission(context, "read")
        handler._send_json({
            "tenant_id": context.tenant_id,
            "messages": handler.services.message_board_service.list_owned(
                context.tenant_id, context.user_id, first_query_value(params, "page_key") or ""
            ),
        })
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_message_board_admin_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_message_board_admin(context)
        result = handler.services.message_board_service.list_all(
            tenant_id=context.tenant_id,
            query=first_query_value(params, "query") or "",
            page=int(first_query_value(params, "page") or 1),
            page_size=int(first_query_value(params, "page_size") or 50),
            status=first_query_value(params, "status") or "",
            sort=first_query_value(params, "sort") or "",
        )
        handler._send_json({"tenant_id": context.tenant_id, **result})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_message_board_create(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_message_board_permission(context, "create")
        message = handler.services.message_board_service.create(context.tenant_id, context.user_id, payload)
        handler._write_audit(context, "message_board.create", "message_board_entry", message["message_id"], {
            "page_key": message["page_key"], "has_quote": bool(message["quote_context"]),
            "attachment_count": len(message["attachment_ids"]),
        })
        handler._send_json({"tenant_id": context.tenant_id, "message": message})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_message_board_update(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_message_board_permission(context, "manage")
        message = handler.services.message_board_service.update(context.tenant_id, context.user_id, payload)
        handler._write_audit(context, "message_board.update", "message_board_entry", message["message_id"], {
            "lock_version": message["lock_version"], "attachment_count": len(message["attachment_ids"]),
        })
        handler._send_json({"tenant_id": context.tenant_id, "message": message})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_message_board_archive(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_message_board_permission(context, "manage")
        message = handler.services.message_board_service.archive(context.tenant_id, context.user_id, payload)
        handler._write_audit(context, "message_board.archive", "message_board_entry", message["message_id"], {
            "status": message["status"], "lock_version": message["lock_version"],
        })
        handler._send_json({"tenant_id": context.tenant_id, "message": message})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_message_board_delete(handler: Any, _query: str = "") -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_message_board_permission(context, "manage")
        message = handler.services.message_board_service.delete(context.tenant_id, context.user_id, payload)
        handler._write_audit(context, "message_board.delete", "message_board_entry", message["message_id"], {
            "page_key": message["page_key"], "lock_version": message["lock_version"],
        })
        handler._send_json({"tenant_id": context.tenant_id, "deleted_message_id": message["message_id"]})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_message_board_admin_append_content_update(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_message_board_admin(context)
        message = handler.services.message_board_service.set_append_content(payload, tenant_id=context.tenant_id)
        handler._write_audit(context, "message_board.append_content.update", "message_board_entry", message["message_id"], {
            "lock_version": message["lock_version"],
        })
        handler._send_json({"tenant_id": context.tenant_id, "message": message})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_message_board_admin_export(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_message_board_admin(context)
        status = (first_query_value(params, "status") or "adopted").strip().lower()
        if status != "adopted":
            raise ValueError("invalid_message_board_export_status")
        export_format = (first_query_value(params, "format") or "excel").strip().lower()
        if export_format not in {"excel", "xlsx", "feishu"}:
            raise ValueError("invalid_message_board_export_format")
        filename = "已采纳留言-飞书表格.xlsx" if export_format == "feishu" else "已采纳留言.xlsx"
        ascii_name = "adopted-messages-feishu.xlsx" if export_format == "feishu" else "adopted-messages.xlsx"

        def load_image(tenant_id: str, attachment_id: str) -> bytes:
            _metadata, content = handler.services.knowledge_service.get_message_board_image_content(tenant_id, attachment_id)
            return content

        body, count = handler.services.message_board_service.export_adopted(
            tenant_id=context.tenant_id,
            load_image=load_image,
        )
        handler._write_audit(context, "message_board.adopted.export", "message_board_entry", "", {
            "count": count, "format": export_format,
        })
        handler._send_bytes(
            body,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}",
                "X-Export-Count": str(count),
            },
        )
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_message_board_admin_status_update(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_message_board_admin(context)
        message = handler.services.message_board_service.set_status(payload, tenant_id=context.tenant_id)
        handler._write_audit(context, "message_board.status.update", "message_board_entry", message["message_id"], {
            "status": message["status"], "lock_version": message["lock_version"],
        })
        handler._send_json({"tenant_id": context.tenant_id, "message": message})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_message_board_image_upload(handler: Any) -> None:
    try:
        payload = handler._read_json(max_bytes=8 * 1024 * 1024)
        context = handler._request_context(payload=payload)
        handler._require_message_board_permission(context, "create")
        result = handler.services.knowledge_service.upload_message_board_image(context.tenant_id, payload, context.user_id)
        attachment = result.get("attachment") if isinstance(result.get("attachment"), dict) else {}
        handler._write_audit(context, "message_board.image.upload", "file_attachment", str(attachment.get("attachment_id") or ""), {
            "message_id": str(payload.get("message_id") or payload.get("messageId") or ""),
            "scan_status": result.get("status"),
        })
        handler._send_json({"tenant_id": context.tenant_id, **result})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_message_board_attachment_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_message_board_permission(context, "read")
        attachment_id = first_query_value(params, "attachment_id") or ""
        if not attachment_id:
            raise ValueError("attachment_id_required")
        metadata, content = handler.services.knowledge_service.get_message_board_image_content(context.tenant_id, attachment_id)
        attachment = metadata["attachment"]
        if attachment.get("owner_user_id") != context.user_id:
            handler._require_message_board_admin(context)
        artifact = metadata["artifact"]
        safe_name = str(attachment.get("file_name") or attachment_id).replace('"', "")
        handler._send_bytes(content, content_type=str(artifact.get("content_type") or "application/octet-stream"), headers={
            "Content-Disposition": f'inline; filename="{safe_name}"', "ETag": f'"{artifact.get("content_hash")}"',
        })
    except Exception as exc:
        send_route_exception(handler, exc)
