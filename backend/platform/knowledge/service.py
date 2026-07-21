from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Any

from .files import build_document_ocr_extractor, build_document_scanner, detect_document_type, parse_document


class KnowledgeService:
    max_upload_bytes = 8 * 1024 * 1024
    max_report_image_bytes = 5 * 1024 * 1024

    def __init__(self, store: Any, acquisition_store: Any, object_store: Any, environment: str) -> None:
        self.store = store
        self.acquisition_store = acquisition_store
        self.object_store = object_store
        self.scanner = build_document_scanner(environment)
        self.ocr_extractor = build_document_ocr_extractor()

    def create_text_document(self, tenant_id: str, payload: dict[str, Any], actor_user_id: str) -> dict[str, Any]:
        return self.store.create_document(tenant_id, payload, actor_user_id)

    def upload_document(self, tenant_id: str, payload: dict[str, Any], actor_user_id: str) -> dict[str, Any]:
        file_name = str(payload.get("file_name") or payload.get("fileName") or "").strip()
        if not file_name or len(file_name) > 500 or "/" in file_name or "\\" in file_name:
            raise ValueError("invalid_file_name")
        encoded = str(payload.get("content_base64") or payload.get("contentBase64") or "").strip()
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("invalid_content_base64") from exc
        if not content or len(content) > self.max_upload_bytes:
            raise ValueError("invalid_document_upload_size")
        detected_content_type, parser_type = detect_document_type(file_name, content)
        document_id = str(payload.get("document_id") or f"kd_{hashlib.sha256((tenant_id + file_name).encode()).hexdigest()[:20]}")
        scan = self.scanner.scan(content)
        stored = self.object_store.put(tenant_id, content, suffix=_suffix(file_name))
        artifact_status = "active" if scan.status == "clean" else "quarantined"
        artifact = self.acquisition_store.create_artifact(
            tenant_id,
            object_uri=stored.object_uri,
            content_hash=stored.content_hash,
            content_type=detected_content_type,
            size_bytes=stored.size_bytes,
            status=artifact_status,
            created_by=actor_user_id,
            artifact_type="document",
        )
        ensure_reference = getattr(self.store, "ensure_artifact_reference", None)
        if callable(ensure_reference):
            ensure_reference(tenant_id, artifact["artifact_id"])
        attachment = self.store.create_attachment(
            tenant_id,
            artifact_id=artifact["artifact_id"],
            owner_user_id=actor_user_id,
            resource_id=document_id,
            file_name=file_name,
            detected_content_type=detected_content_type,
            scan_status=scan.status,
            processing_status="processing" if scan.status == "clean" else "failed",
            classification=str(payload.get("classification") or "internal"),
        )
        if scan.status != "clean":
            return {
                "status": "quarantined",
                "artifact": _public_artifact(artifact),
                "attachment": attachment,
                "scan": {"status": scan.status, "engine": scan.engine, "signature": scan.signature},
            }
        try:
            text, parser_name = parse_document(content, parser_type)
        except Exception as exc:
            should_try_ocr = parser_type == "ocr_image" or (
                parser_type == "pdf" and str(exc) == "pdf_has_no_extractable_text"
            )
            if not should_try_ocr:
                self.store.update_attachment_processing(
                    tenant_id,
                    attachment["attachment_id"],
                    "failed",
                    error_code=(str(exc) if isinstance(exc, ValueError) and str(exc) in {"unsupported_document_type"} else "document_parse_failed"),
                )
                raise
            if self.ocr_extractor is None:
                self.store.update_attachment_processing(
                    tenant_id,
                    attachment["attachment_id"],
                    "failed",
                    error_code="ocr_provider_required_for_scanned_document",
                )
                raise RuntimeError("ocr_provider_required_for_scanned_document") from exc
            try:
                text, parser_name = self.ocr_extractor.extract(content, detected_content_type)
            except Exception as ocr_exc:
                self.store.update_attachment_processing(
                    tenant_id,
                    attachment["attachment_id"],
                    "failed",
                    error_code="ocr_extraction_failed",
                )
                raise RuntimeError("ocr_extraction_failed") from ocr_exc
        parsed_object = self.object_store.put(tenant_id, text.encode("utf-8"), suffix=".txt")
        parsed_artifact = self.acquisition_store.create_artifact(
            tenant_id,
            object_uri=parsed_object.object_uri,
            content_hash=parsed_object.content_hash,
            content_type="text/plain; charset=utf-8",
            size_bytes=parsed_object.size_bytes,
            status="active",
            created_by=actor_user_id,
            artifact_type="document",
        )
        if callable(ensure_reference):
            ensure_reference(tenant_id, parsed_artifact["artifact_id"])
        document = self.store.create_document(
            tenant_id,
            {**payload, "document_id": document_id, "title": payload.get("title") or file_name},
            actor_user_id,
            content=text,
            source_attachment_id=attachment["attachment_id"],
            content_artifact_id=parsed_artifact["artifact_id"],
            parser_name=parser_name,
        )
        attachment = self.store.update_attachment_processing(
            tenant_id,
            attachment["attachment_id"],
            "ready",
            error_code="",
        )
        return {
            "status": "review",
            "document": document,
            "artifact": _public_artifact(artifact),
            "parsed_artifact": _public_artifact(parsed_artifact),
            "attachment": attachment,
            "scan": {"status": scan.status, "engine": scan.engine},
        }

    def review_document(self, tenant_id: str, document_id: str, decision: str, actor_user_id: str) -> dict[str, Any]:
        return self.store.review_document(tenant_id, document_id, decision, actor_user_id)

    def upload_report_image(self, tenant_id: str, payload: dict[str, Any], actor_user_id: str) -> dict[str, Any]:
        file_name = str(payload.get("file_name") or payload.get("fileName") or "").strip()
        if not file_name or len(file_name) > 500 or "/" in file_name or "\\" in file_name:
            raise ValueError("invalid_file_name")
        encoded = str(payload.get("content_base64") or payload.get("contentBase64") or "").strip()
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("invalid_content_base64") from exc
        if not content or len(content) > self.max_report_image_bytes:
            raise ValueError("invalid_report_image_size")
        content_type, suffix = _detect_safe_image(content)
        report_id = str(payload.get("report_id") or payload.get("reportId") or "").strip()
        block_id = str(payload.get("block_id") or payload.get("blockId") or "").strip()
        if not report_id or not block_id:
            raise ValueError("report_image_resource_required")
        scan = self.scanner.scan(content)
        stored = self.object_store.put(tenant_id, content, suffix=suffix)
        artifact = self.acquisition_store.create_artifact(
            tenant_id,
            object_uri=stored.object_uri,
            content_hash=stored.content_hash,
            content_type=content_type,
            size_bytes=stored.size_bytes,
            status="active" if scan.status == "clean" else "quarantined",
            created_by=actor_user_id,
            artifact_type="image",
        )
        ensure_reference = getattr(self.store, "ensure_artifact_reference", None)
        if callable(ensure_reference):
            ensure_reference(tenant_id, artifact["artifact_id"])
        attachment = self.store.create_attachment(
            tenant_id,
            artifact_id=artifact["artifact_id"],
            owner_user_id=actor_user_id,
            resource_id=f"{report_id}:{block_id}",
            resource_type="weekly_report_image",
            file_name=file_name,
            detected_content_type=content_type,
            scan_status=scan.status,
            processing_status="ready" if scan.status == "clean" else "failed",
            classification=str(payload.get("classification") or "internal"),
        )
        return {
            "status": "ready" if scan.status == "clean" else "quarantined",
            "attachment": attachment,
            "artifact": _public_artifact(artifact),
            "content_url": f"/api/attachments/content?attachment_id={attachment['attachment_id']}",
            "scan": {"status": scan.status, "engine": scan.engine, "signature": scan.signature},
        }

    def get_report_image_content(self, tenant_id: str, attachment_id: str) -> tuple[dict[str, Any], bytes]:
        attachment = self.store.get_attachment(tenant_id, attachment_id)
        if attachment.get("resource_type") != "weekly_report_image":
            raise PermissionError("attachment_resource_type_mismatch")
        if attachment.get("scan_status") != "clean" or attachment.get("processing_status") != "ready":
            raise PermissionError("attachment_is_not_publishable")
        artifact, content = self.object_store_artifact(tenant_id, str(attachment["artifact_id"]))
        return {"attachment": attachment, "artifact": _public_artifact(artifact)}, content

    def object_store_artifact(self, tenant_id: str, artifact_id: str) -> tuple[dict[str, Any], bytes]:
        artifact = self.acquisition_store.get_artifact(tenant_id, artifact_id)
        if artifact.get("status") != "active":
            raise PermissionError("artifact_is_not_publishable")
        content = self.object_store.read(tenant_id, artifact["object_uri"], artifact["content_hash"])
        return artifact, content

    def list_documents(self, tenant_id: str) -> list[dict[str, Any]]:
        return self.store.list_documents(tenant_id)

    def search(self, tenant_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return [
            {
                "document_id": hit.document.doc_id,
                "title": hit.document.title,
                "content": hit.document.content,
                "version_no": hit.document.version_no,
                "chunk_id": hit.chunk_id,
                "knowledge_version_id": hit.knowledge_version_id,
                "locator": hit.locator,
                "score": hit.score,
                "matched_terms": list(hit.matched_terms),
            }
            for hit in self.store.search(query, tenant_id=tenant_id, limit=limit)
        ]


def _suffix(file_name: str) -> str:
    suffix = "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ".bin"
    return suffix if len(suffix) <= 12 else ".bin"


def _detect_safe_image(content: bytes) -> tuple[str, str]:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif", ".gif"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp", ".webp"
    raise ValueError("unsupported_or_invalid_report_image")


def _public_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        key: artifact.get(key)
        for key in ("artifact_id", "artifact_type", "content_hash", "content_type", "size_bytes", "status", "created_at")
    }
