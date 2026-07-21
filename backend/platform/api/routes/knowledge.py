from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import first_query_value, send_route_exception


def handle_knowledge_documents_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_knowledge_permission(context, "read")
        documents = handler.services.knowledge_service.list_documents(context.tenant_id)
        handler._send_json({"tenant_id": context.tenant_id, "documents": documents, "count": len(documents)})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_knowledge_search_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_knowledge_permission(context, "read")
        query_text = first_query_value(params, "q") or first_query_value(params, "query") or ""
        limit = int(first_query_value(params, "limit") or 5)
        hits = handler.services.knowledge_service.search(context.tenant_id, query_text, limit)
        handler._send_json({"tenant_id": context.tenant_id, "query": query_text, "hits": hits, "count": len(hits)})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_knowledge_document_create(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_knowledge_permission(context, "create")
        document = handler.services.knowledge_service.create_text_document(context.tenant_id, payload, context.user_id)
        handler._write_audit(
            context,
            "knowledge.document.create",
            "knowledge_document",
            document["document_id"],
            {"version_no": document["current_version_no"], "status": document["status"]},
        )
        handler._send_json({"tenant_id": context.tenant_id, "document": document})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_knowledge_document_upload(handler: Any) -> None:
    try:
        payload = handler._read_json(max_bytes=12 * 1024 * 1024)
        context = handler._request_context(payload=payload)
        handler._require_knowledge_permission(context, "create")
        result = handler.services.knowledge_service.upload_document(context.tenant_id, payload, context.user_id)
        document = result.get("document", {}) if isinstance(result.get("document"), dict) else {}
        attachment = result.get("attachment", {}) if isinstance(result.get("attachment"), dict) else {}
        handler._write_audit(
            context,
            "knowledge.document.upload",
            "knowledge_document",
            str(document.get("document_id") or attachment.get("resource_id") or ""),
            {
                "status": result.get("status"),
                "scan_status": result.get("scan", {}).get("status") if isinstance(result.get("scan"), dict) else "",
                "content_hash": result.get("artifact", {}).get("content_hash") if isinstance(result.get("artifact"), dict) else "",
            },
        )
        handler._send_json({"tenant_id": context.tenant_id, **result})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_knowledge_document_review(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_knowledge_permission(context, "manage")
        document_id = str(payload.get("document_id") or "").strip()
        decision = str(payload.get("decision") or "").strip()
        document = handler.services.knowledge_service.review_document(
            context.tenant_id,
            document_id,
            decision,
            context.user_id,
        )
        handler._write_audit(
            context,
            "knowledge.document.review",
            "knowledge_document",
            document_id,
            {"decision": decision, "status": document["status"], "version_no": document["current_version_no"]},
        )
        handler._send_json({"tenant_id": context.tenant_id, "document": document})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)
