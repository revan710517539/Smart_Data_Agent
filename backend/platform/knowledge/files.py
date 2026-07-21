from __future__ import annotations

import io
import base64
import json
import os
import socket
import ssl
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request

import certifi

from backend.platform.security import safe_urlopen


@dataclass(frozen=True)
class ScanResult:
    status: str
    engine: str
    signature: str = ""


class DevelopmentDocumentScanner:
    """Fail-closed basic scanner for local development only."""

    def scan(self, content: bytes) -> ScanResult:
        if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in content.upper():
            return ScanResult("infected", "development-signature", "EICAR-Test-Signature")
        return ScanResult("clean", "development-signature")


class ClamAVDocumentScanner:
    def __init__(self, host: str, port: int = 3310, timeout_seconds: float = 15.0) -> None:
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds

    def scan(self, content: bytes) -> ScanResult:
        with socket.create_connection((self.host, self.port), timeout=self.timeout_seconds) as client:
            client.sendall(b"zINSTREAM\0")
            for offset in range(0, len(content), 64 * 1024):
                chunk = content[offset : offset + 64 * 1024]
                client.sendall(len(chunk).to_bytes(4, "big") + chunk)
            client.sendall((0).to_bytes(4, "big"))
            response = client.recv(4096).decode("utf-8", errors="replace").strip("\0\r\n")
        if response.endswith(" OK"):
            return ScanResult("clean", "clamav")
        if " FOUND" in response:
            signature = response.rsplit(":", 1)[-1].replace("FOUND", "").strip()
            return ScanResult("infected", "clamav", signature)
        return ScanResult("failed", "clamav", response[:200])


def build_document_scanner(environment: str) -> DevelopmentDocumentScanner | ClamAVDocumentScanner:
    host = os.getenv("SMART_DATA_AGENT_CLAMAV_HOST", "").strip()
    if host:
        return ClamAVDocumentScanner(host, int(os.getenv("SMART_DATA_AGENT_CLAMAV_PORT", "3310")))
    if environment == "production":
        raise RuntimeError("production_document_scanner_required")
    return DevelopmentDocumentScanner()


class HTTPDocumentOCRExtractor:
    """Outbound-policy protected OCR adapter for scanned PDFs and images."""

    def __init__(self, endpoint: str, api_key: str = "", timeout_seconds: float = 45.0) -> None:
        self.endpoint = str(endpoint or "").strip()
        self.api_key = str(api_key or "").strip()
        self.timeout_seconds = max(5.0, min(float(timeout_seconds), 120.0))
        if not self.endpoint:
            raise ValueError("ocr_endpoint_required")

    def extract(self, content: bytes, content_type: str) -> tuple[str, str]:
        body = json.dumps(
            {
                "content_base64": base64.b64encode(content).decode("ascii"),
                "content_type": content_type,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "SmartDataAgent/1.0 ocr",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.endpoint, data=body, headers=headers, method="POST")
        with safe_urlopen(
            request,
            timeout=self.timeout_seconds,
            context=ssl.create_default_context(cafile=certifi.where()),
        ) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise RuntimeError("ocr_response_too_large")
        payload: Any = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("ocr_response_invalid")
        text = str(payload.get("text") or "").strip()
        if not text:
            pages = payload.get("pages")
            if isinstance(pages, list):
                text = "\n\n".join(
                    str(page.get("text") or "").strip()
                    for page in pages
                    if isinstance(page, dict) and str(page.get("text") or "").strip()
                )
        if not text:
            raise ValueError("ocr_has_no_extractable_text")
        engine = str(payload.get("engine") or payload.get("model") or "external_ocr")[:120]
        return text, f"ocr:{engine}"


def build_document_ocr_extractor() -> HTTPDocumentOCRExtractor | None:
    endpoint = os.getenv("SMART_DATA_AGENT_OCR_ENDPOINT", "").strip()
    if not endpoint:
        return None
    return HTTPDocumentOCRExtractor(
        endpoint,
        os.getenv("SMART_DATA_AGENT_OCR_API_KEY", ""),
        float(os.getenv("SMART_DATA_AGENT_OCR_TIMEOUT_SECONDS", "45")),
    )


def detect_document_type(file_name: str, content: bytes) -> tuple[str, str]:
    suffix = Path(file_name).suffix.lower()
    if content.startswith(b"%PDF-"):
        return "application/pdf", "pdf"
    if content.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = set(archive.namelist())
            if "word/document.xml" in names:
                return "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"
        except zipfile.BadZipFile:
            pass
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "ocr_image"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "ocr_image"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif", "ocr_image"
    if suffix == ".csv":
        return "text/csv", "text"
    if suffix in {".md", ".markdown"}:
        return "text/markdown", "text"
    if suffix == ".json":
        return "application/json", "text"
    try:
        content.decode("utf-8")
        return "text/plain", "text"
    except UnicodeDecodeError:
        return "application/octet-stream", "unsupported"


def parse_document(content: bytes, parser_type: str) -> tuple[str, str]:
    if parser_type == "text":
        return content.decode("utf-8-sig"), "utf8_text"
    if parser_type == "pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - dependency contract.
            raise RuntimeError("pdf_parser_dependency_missing") from exc
        reader = PdfReader(io.BytesIO(content))
        text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
        if not text:
            raise ValueError("pdf_has_no_extractable_text")
        return text, f"pypdf:{len(reader.pages)}pages"
    if parser_type == "docx":
        try:
            from docx import Document
        except ImportError as exc:  # pragma: no cover - dependency contract.
            raise RuntimeError("docx_parser_dependency_missing") from exc
        document = Document(io.BytesIO(content))
        lines = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        for table in document.tables:
            for row in table.rows:
                lines.append("\t".join(cell.text.strip() for cell in row.cells))
        text = "\n".join(lines).strip()
        if not text:
            raise ValueError("docx_has_no_extractable_text")
        return text, "python-docx"
    raise ValueError("unsupported_document_type")
