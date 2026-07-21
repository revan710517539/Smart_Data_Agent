from __future__ import annotations

import base64
import hashlib
import hmac
from http.cookies import SimpleCookie
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import unquote


AuthMode = Literal["development", "strict"]
TOKEN_PREFIX = "sda1"


class AuthenticationError(ValueError):
    """Raised when an API request cannot be tied to a trusted user context."""


@dataclass(frozen=True)
class SignedSession:
    user_id: str
    tenant_id: str
    tenant_ids: tuple[str, ...] = ()
    expires_at: int | None = None
    session_id: str = ""
    device_session_id: str = ""
    issuer: str = ""
    audience: str = ""


def resolve_request_context(
    headers: dict[str, str | None],
    payload: dict[str, Any] | None = None,
    params: dict[str, list[str]] | None = None,
    default_user_id: str | None = None,
    default_tenant_id: str | None = None,
    mode: AuthMode | None = None,
) -> SignedSession:
    """Resolve request identity.

    In strict mode, only a signed bearer token is trusted. Development mode
    keeps the existing local workflow alive while moving callers toward headers.
    """

    auth_mode = mode or _auth_mode_from_env()
    bearer = _bearer_token(headers.get("authorization") or headers.get("Authorization"))
    cookie_token = _session_cookie_token(headers.get("cookie") or headers.get("Cookie"))
    trusted_token = bearer or cookie_token
    if trusted_token:
        session = verify_session_token(trusted_token)
        requested_tenant_id = _first_non_empty(
            headers.get("x-tenant-id") or headers.get("X-Tenant-Id"),
            _first_query_value(params or {}, "tenant_id"),
        )
        if requested_tenant_id and requested_tenant_id != session.tenant_id:
            allowed_tenant_ids = set(session.tenant_ids or (session.tenant_id,))
            if requested_tenant_id not in allowed_tenant_ids:
                raise AuthenticationError("tenant is not authorized for this session.")
            return SignedSession(
                user_id=session.user_id,
                tenant_id=requested_tenant_id,
                tenant_ids=session.tenant_ids,
                expires_at=session.expires_at,
                session_id=session.session_id,
                device_session_id=session.device_session_id,
                issuer=session.issuer,
                audience=session.audience,
            )
        return session
    if auth_mode == "strict":
        raise AuthenticationError("authentication token is required.")

    payload = payload or {}
    params = params or {}
    user_id = _first_non_empty(
        headers.get("x-user-id") or headers.get("X-User-Id"),
        payload.get("user_id"),
        _first_query_value(params, "user_id"),
        default_user_id,
    )
    tenant_id = _first_non_empty(
        headers.get("x-tenant-id") or headers.get("X-Tenant-Id"),
        payload.get("tenant_id"),
        _first_query_value(params, "tenant_id"),
        default_tenant_id,
    )
    if not user_id or not tenant_id:
        raise AuthenticationError("request context is incomplete.")
    return SignedSession(user_id=user_id, tenant_id=tenant_id)


def make_session_token(
    user_id: str,
    tenant_id: str,
    tenant_ids: tuple[str, ...] | list[str] | set[str] | None = None,
    secret: str | None = None,
    ttl_seconds: int | None = None,
    issued_at: int | None = None,
    session_id: str | None = None,
    device_session_id: str | None = None,
) -> str:
    if not user_id or not tenant_id:
        raise ValueError("user_id and tenant_id are required.")
    now = int(time.time() if issued_at is None else issued_at)
    payload: dict[str, Any] = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "iat": now,
        "iss": _token_issuer(),
        "aud": _token_audience(),
        "jti": session_id or secrets.token_urlsafe(24),
        "kid": os.getenv("SMART_DATA_AGENT_AUTH_KEY_ID", "local-v1").strip() or "local-v1",
    }
    if device_session_id:
        payload["sid"] = device_session_id
    normalized_tenant_ids = _normalize_tenant_ids(tenant_ids or (tenant_id,))
    if normalized_tenant_ids:
        payload["tenant_ids"] = list(normalized_tenant_ids)
    if ttl_seconds is not None:
        payload["exp"] = now + ttl_seconds
    payload_part = _b64encode(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    signature = _sign(payload_part, _auth_secret(secret))
    return f"{TOKEN_PREFIX}.{payload_part}.{signature}"


def verify_session_token(token: str, secret: str | None = None, now: int | None = None) -> SignedSession:
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        raise AuthenticationError("invalid authentication token.")
    payload_part = parts[1]
    expected_signature = _sign(payload_part, _auth_secret(secret))
    if not hmac.compare_digest(parts[2], expected_signature):
        raise AuthenticationError("invalid authentication signature.")
    try:
        payload = json.loads(_b64decode(payload_part).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthenticationError("invalid authentication payload.") from exc
    user_id = str(payload.get("user_id") or "").strip()
    tenant_id = str(payload.get("tenant_id") or "").strip()
    tenant_ids = _normalize_tenant_ids(payload.get("tenant_ids") or (tenant_id,))
    expires_at = payload.get("exp")
    issued_at = payload.get("iat")
    issuer = str(payload.get("iss") or "").strip()
    audience = str(payload.get("aud") or "").strip()
    session_id = str(payload.get("jti") or "").strip()
    device_session_id = str(payload.get("sid") or "").strip()
    if not user_id or not tenant_id:
        raise AuthenticationError("authentication payload missing user or tenant.")
    if issuer != _token_issuer() or audience != _token_audience() or not session_id:
        raise AuthenticationError("authentication token issuer, audience, or session id is invalid.")
    current_time = int(now or time.time())
    if issued_at is None or int(issued_at) > current_time + 60:
        raise AuthenticationError("authentication token issue time is invalid.")
    if _auth_mode_from_env() == "strict" and expires_at is None:
        raise AuthenticationError("strict authentication token must expire.")
    if tenant_id not in tenant_ids:
        tenant_ids = (tenant_id, *tenant_ids)
    if expires_at is not None and int(expires_at) <= current_time:
        raise AuthenticationError("authentication token expired.")
    return SignedSession(
        user_id=user_id,
        tenant_id=tenant_id,
        tenant_ids=tenant_ids,
        expires_at=int(expires_at) if expires_at else None,
        session_id=session_id,
        device_session_id=device_session_id,
        issuer=issuer,
        audience=audience,
    )


def _auth_mode_from_env() -> AuthMode:
    mode = os.getenv("SMART_DATA_AGENT_AUTH_MODE", "development").strip().lower()
    return "strict" if mode == "strict" else "development"


def _auth_secret(secret: str | None = None) -> str:
    value = (secret or os.getenv("SMART_DATA_AGENT_AUTH_SECRET") or "").strip()
    if value:
        return value
    if _auth_mode_from_env() == "strict":
        raise AuthenticationError("SMART_DATA_AGENT_AUTH_SECRET is required in strict auth mode.")
    return "smart-data-agent-local-dev-secret"


def _token_issuer() -> str:
    return os.getenv("SMART_DATA_AGENT_AUTH_ISSUER", "smart-data-agent").strip() or "smart-data-agent"


def _token_audience() -> str:
    return os.getenv("SMART_DATA_AGENT_AUTH_AUDIENCE", "smart-data-agent-api").strip() or "smart-data-agent-api"


def _sign(payload_part: str, secret: str) -> str:
    signature = hmac.new(secret.encode("utf-8"), payload_part.encode("utf-8"), hashlib.sha256).digest()
    return _b64encode(signature)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def _bearer_token(value: str | None) -> str | None:
    if not value:
        return None
    scheme, _, token = value.strip().partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _session_cookie_token(value: str | None) -> str | None:
    if not value:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(value)
    except Exception:
        return None
    morsel = cookie.get("sda_session")
    return morsel.value.strip() if morsel and morsel.value.strip() else None


def _first_query_value(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    return values[0] if values else None


def _first_non_empty(*candidates: Any) -> str | None:
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return unquote(value)
    return None


def _normalize_tenant_ids(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, (list, tuple, set)):
        candidates = list(value)
    else:
        candidates = []
    normalized: list[str] = []
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        text = unquote(text)
        if text not in normalized:
            normalized.append(text)
    return tuple(normalized)
