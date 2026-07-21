from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

from .contracts import CrawlerDiagnostic, CrawlerErrorCode


_SENSITIVE_KEY = re.compile(r"password|passwd|secret|token|authorization|cookie|credential", re.IGNORECASE)
_BEARER = re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+")
_BASIC = re.compile(r"(?i)basic\s+[a-z0-9+/=]+")


def redact_text(value: Any, secrets: Iterable[str] = ()) -> str:
    text = str(value or "")
    for secret in sorted({str(item) for item in secrets if str(item)}, key=len, reverse=True):
        text = text.replace(secret, "******")
    text = _BEARER.sub("Bearer ******", text)
    text = _BASIC.sub("Basic ******", text)
    return text[:8_000]


def sanitize_mapping(value: Any, secrets: Iterable[str] = ()) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "******" if _SENSITIVE_KEY.search(str(key)) else sanitize_mapping(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_mapping(item, secrets) for item in value[:100]]
    if isinstance(value, tuple):
        return tuple(sanitize_mapping(item, secrets) for item in value[:100])
    if isinstance(value, str):
        return redact_text(value, secrets)
    return value


def classify_exception(exc: Exception, failed_step: str = "") -> tuple[str, bool]:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if "bbtl5022" in message or "rate limit" in message or "访问过于频繁" in message:
        return CrawlerErrorCode.RATE_LIMITED, True
    if "timeout" in name or "timeout" in message:
        return CrawlerErrorCode.NETWORK_ERROR, True
    if "download" in failed_step or "download" in message:
        return CrawlerErrorCode.CSV_DOWNLOAD_FAILED, True
    if "login" in failed_step or "password" in message or "credential" in message:
        return CrawlerErrorCode.LOGIN_FAILED, False
    if "selector" in message or "strict mode" in message or "not found" in message:
        return CrawlerErrorCode.PAGE_CHANGED, False
    if "captcha" in message or "mfa" in message or "verification" in message:
        return CrawlerErrorCode.MANUAL_INTERVENTION_REQUIRED, False
    return CrawlerErrorCode.UNKNOWN_ERROR, False


def build_diagnostic(
    exc: Exception,
    *,
    failed_step: str,
    secrets: Iterable[str] = (),
    page_url: str = "",
    page_title: str = "",
    dom_summary: str = "",
    screenshot: bytes | None = None,
    network_summary: list[dict[str, Any]] | None = None,
) -> CrawlerDiagnostic:
    error_code, retryable = classify_exception(exc, failed_step)
    safe_network = sanitize_mapping(network_summary or [], secrets)
    return CrawlerDiagnostic(
        error_code=str(error_code),
        summary=redact_text(str(exc) or type(exc).__name__, secrets),
        failed_step=failed_step,
        page_url=redact_text(page_url, secrets),
        page_title=redact_text(page_title, secrets),
        dom_summary=redact_text(dom_summary, secrets),
        screenshot_sha256=hashlib.sha256(screenshot).hexdigest() if screenshot else "",
        network_summary=tuple(safe_network),
        retryable=retryable,
    )


def stable_json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
