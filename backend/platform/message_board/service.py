from __future__ import annotations

import re
from typing import Any


class MessageBoardService:
    def __init__(self, store: Any, knowledge_store: Any, user_store: Any) -> None:
        self.store = store
        self.knowledge_store = knowledge_store
        self.user_store = user_store

    def create(self, tenant_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        entry = self._entry(tenant_id, user_id, payload)
        self._validate_attachments(tenant_id, user_id, entry["message_id"], entry["attachment_ids"])
        return self._with_author_name(self.store.create(entry))

    def update(self, tenant_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        message_id = _message_id(payload.get("message_id") or payload.get("messageId"))
        content = _text(payload.get("content"), "content", 5000, required=True)
        attachment_ids = _attachment_ids(payload.get("attachment_ids") or payload.get("attachmentIds") or [])
        self._validate_attachments(tenant_id, user_id, message_id, attachment_ids)
        return self._with_author_name(self.store.update(
            tenant_id,
            user_id,
            message_id,
            {
                "content": content,
                "quote_context": _quote_context(payload.get("quote_context") or payload.get("quoteContext")),
                "attachment_ids": attachment_ids,
            },
            int(payload.get("expected_lock_version") if payload.get("expected_lock_version") is not None else payload.get("expectedLockVersion", -1)),
        ))

    def archive(self, tenant_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._with_author_name(self.store.archive_owned(
            tenant_id,
            user_id,
            _message_id(payload.get("message_id") or payload.get("messageId")),
            _lock_version(payload),
        ))

    def delete(self, tenant_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._with_author_name(self.store.delete_owned(
            tenant_id,
            user_id,
            _message_id(payload.get("message_id") or payload.get("messageId")),
            _lock_version(payload),
        ))

    def set_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._with_author_name(self.store.set_status(
            _message_id(payload.get("message_id") or payload.get("messageId")),
            _status(payload.get("status")),
            _lock_version(payload),
        ))

    def list_owned(self, tenant_id: str, user_id: str, page_key: str = "") -> list[dict[str, Any]]:
        return [self._with_author_name(row) for row in self.store.list_owned(tenant_id, user_id, _text(page_key, "page_key", 160))]

    def list_all(self, *, query: str = "", page: int = 1, page_size: int = 50) -> dict[str, Any]:
        safe_page = max(1, min(int(page or 1), 100000))
        safe_size = max(1, min(int(page_size or 50), 100))
        rows, total = self.store.list_all(query=str(query or "")[:200], offset=(safe_page - 1) * safe_size, limit=safe_size)
        return {"messages": [self._with_author_name(row) for row in rows], "total": total, "page": safe_page, "page_size": safe_size}

    def _with_author_name(self, entry: dict[str, Any]) -> dict[str, Any]:
        result = dict(entry)
        author_user_id = str(result.get("author_user_id") or "").strip()
        profile = self.user_store.get_profile(author_user_id) if author_user_id else None
        profile_name = str(getattr(profile, "name", "") or "").strip()
        stored_name = str(result.get("author_name") or "").strip()
        result["author_name"] = profile_name or (stored_name if stored_name and stored_name != author_user_id else "未知用户")
        return result

    def _entry(self, tenant_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        message_id = _message_id(payload.get("message_id") or payload.get("messageId"))
        profile = self.user_store.get_profile(user_id)
        if not profile:
            raise KeyError("message_board_author_not_found")
        return {
            "message_id": message_id,
            "tenant_id": tenant_id,
            "author_user_id": user_id,
            "author_name": _text(getattr(profile, "name", "") or user_id, "author_name", 200, required=True),
            "page_key": _text(payload.get("page_key") or payload.get("pageKey"), "page_key", 160, required=True),
            "page_title": _text(payload.get("page_title") or payload.get("pageTitle"), "page_title", 240, required=True),
            "page_url": _text(payload.get("page_url") or payload.get("pageUrl"), "page_url", 1000),
            "content": _text(payload.get("content"), "content", 5000, required=True),
            "quote_context": _quote_context(payload.get("quote_context") or payload.get("quoteContext")),
            "attachment_ids": _attachment_ids(payload.get("attachment_ids") or payload.get("attachmentIds") or []),
            "status": "new",
        }

    def _validate_attachments(self, tenant_id: str, user_id: str, message_id: str, attachment_ids: list[str]) -> None:
        for attachment_id in attachment_ids:
            attachment = self.knowledge_store.get_attachment(tenant_id, attachment_id)
            if (
                attachment.get("resource_type") != "message_board_image"
                or attachment.get("resource_id") != message_id
                or attachment.get("owner_user_id") != user_id
                or attachment.get("scan_status") != "clean"
                or attachment.get("processing_status") != "ready"
            ):
                raise PermissionError("message_board_attachment_owner_required")


def _message_id(value: Any) -> str:
    normalized = str(value or "").strip()
    if not re.fullmatch(r"mb_[a-f0-9]{32}", normalized):
        raise ValueError("invalid_message_board_id")
    return normalized


def _status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in {"new", "adopted", "completed"}:
        raise ValueError("invalid_message_board_status")
    return normalized


def _lock_version(payload: dict[str, Any]) -> int:
    value = payload.get("expected_lock_version")
    if value is None:
        value = payload.get("expectedLockVersion", -1)
    normalized = int(value)
    if normalized < 0:
        raise ValueError("invalid_message_board_lock_version")
    return normalized


def _text(value: Any, field: str, maximum: int, required: bool = False) -> str:
    normalized = str(value or "").strip()
    if (required and not normalized) or len(normalized) > maximum:
        raise ValueError(f"invalid_message_board_{field}")
    return normalized


def _attachment_ids(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > 5:
        raise ValueError("invalid_message_board_attachments")
    result: list[str] = []
    for item in value:
        attachment_id = str(item or "").strip()
        if not re.fullmatch(r"fa_[a-f0-9]{32}", attachment_id):
            raise ValueError("invalid_message_board_attachment_id")
        if attachment_id not in result:
            result.append(attachment_id)
    return result


def _quote_context(value: Any) -> dict[str, str]:
    if value in (None, "", {}):
        return {}
    if not isinstance(value, dict):
        raise ValueError("invalid_message_board_quote_context")
    selected_text = _text(value.get("selected_text") or value.get("selectedText"), "quote_text", 1000)
    if not selected_text:
        return {}
    return {
        "target_id": _text(value.get("target_id") or value.get("targetId"), "quote_target_id", 200),
        "target_type": _text(value.get("target_type") or value.get("targetType"), "quote_target_type", 40),
        "label": _text(value.get("label"), "quote_label", 240),
        "selected_text": selected_text,
    }
