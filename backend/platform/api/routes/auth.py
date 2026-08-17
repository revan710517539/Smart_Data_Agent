from __future__ import annotations

from http import HTTPStatus
from http.cookies import SimpleCookie
import hashlib
import hmac
import os
from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import send_route_exception
from backend.platform.security import AuthenticationError, make_session_token
from backend.platform.settings import ensure_default_models_for_account


def handle_auth_login(handler: Any) -> None:
    try:
        if handler.services.runtime_config.auth_mode != "development":
            handler._send_json(
                {
                    "error": "external_identity_required",
                    "message": "Strict mode accepts only sessions issued by the configured enterprise identity provider.",
                },
                HTTPStatus.FORBIDDEN,
            )
            return
        payload = handler._read_json()
        email = str(payload.get("email") or "").strip()
        password = str(payload.get("password") or "")
        expected_password = os.getenv("SMART_DATA_AGENT_DEVELOPMENT_LOGIN_PASSWORD", "")
        if not expected_password or not hmac.compare_digest(password, expected_password):
            raise ValueError("invalid_login_credentials")
        tenant_hint = str(payload.get("tenant_id") or payload.get("institution") or "").strip() or None
        session = handler.services.access_service.login_by_email(email, tenant_hint=tenant_hint)
        response, cookies = _issue_session(handler, session)
        user = session.get("user") if isinstance(session.get("user"), dict) else {}
        try:
            handler.services.interaction_event_store.write(
                tenant_id=str(session.get("tenant_id") or ""),
                actor_user_id=str(user.get("id") or ""),
                actor_account=str(user.get("email") or email),
                event_name="login_submit",
                event_type="click",
                page_path="/login",
                page_name="登录",
                resource_type="authentication",
                extension={"outcome": "success"},
            )
        except Exception:
            # Telemetry is best effort. A metrics-table outage must never turn a
            # valid authentication result into a failed login.
            pass
        handler._send_json(response, headers={"Set-Cookie": cookies})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_auth_register(handler: Any) -> None:
    try:
        if handler.services.runtime_config.auth_mode != "development":
            handler._send_json(
                {
                    "error": "public_registration_disabled",
                    "message": "Accounts must be invited or provisioned by an administrator.",
                },
                HTTPStatus.FORBIDDEN,
            )
            return
        payload = handler._read_json()
        session = handler.services.access_service.register_operator_by_email(payload)
        user = session.get("user") if isinstance(session.get("user"), dict) else {}
        ensure_default_models_for_account(
            handler.services.system_config_store,
            str(user.get("id") or ""),
            updated_by="system",
        )
        response, cookies = _issue_session(handler, session)
        handler._send_json(
            response,
            HTTPStatus.CREATED,
            headers={"Set-Cookie": cookies},
        )
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_auth_logout(handler: Any) -> None:
    cookies = _request_cookies(handler)
    refresh_token = cookies.get("sda_refresh", "")
    access_token = cookies.get("sda_session", "")
    access_jti = ""
    if access_token:
        try:
            from backend.platform.security import verify_session_token

            access_jti = verify_session_token(access_token).session_id
        except AuthenticationError:
            access_jti = ""
    handler.services.session_store.revoke(
        access_jti=access_jti,
        refresh_token=refresh_token,
        reason="logout",
    )
    handler._send_json(
        {"status": "logged_out"},
        headers={"Set-Cookie": _clear_session_cookies(handler.services.runtime_config.is_production)},
    )


def handle_auth_refresh(handler: Any) -> None:
    try:
        refresh_token = _request_cookies(handler).get("sda_refresh", "")
        if not refresh_token:
            raise AuthenticationError("refresh_token_required")
        grant = handler.services.session_store.rotate_refresh(
            refresh_token,
            access_ttl_seconds=_access_ttl_seconds(),
        )
        session = handler.services.access_service.session_for_user(
            grant.user_id,
            tenant_hint=grant.primary_tenant_id,
        )
        token = _token_for_grant(grant)
        handler._send_json(
            {
                "status": "refreshed",
                "expires_at": grant.access_expires_at,
                "session": session,
            },
            headers={"Set-Cookie": _session_cookies(token, grant.refresh_token, handler.services.runtime_config.is_production)},
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_auth_me(handler: Any, query: str = "") -> None:
    del query
    try:
        cookies = _request_cookies(handler)
        authorization = str(handler.headers.get("Authorization") or "").strip()
        if not cookies.get("sda_session") and not authorization.lower().startswith("bearer "):
            raise AuthenticationError("authentication token is required.")
        context = handler._request_context()
        session = handler.services.access_service.session_for_user(context.user_id, tenant_hint=context.tenant_id)
        handler._send_json(session)
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_auth_oidc_start(handler: Any, query: str = "") -> None:
    del query
    try:
        payload = handler.services.oidc_client.start()
        handler._send_json(payload)
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_auth_oidc_callback(handler: Any, query: str = "") -> None:
    try:
        params = parse_qs(query)
        if params.get("error"):
            raise AuthenticationError("oidc_provider_denied_authorization")
        code = str((params.get("code") or [""])[0]).strip()
        state = str((params.get("state") or [""])[0]).strip()
        identity = handler.services.oidc_client.exchange_code(code, state)
        session = handler.services.access_service.login_by_email(str(identity["email"]))
        _, cookies = _issue_session(handler, session)
        redirect_target = os.getenv("SMART_DATA_AGENT_POST_LOGIN_URL", "/").strip() or "/"
        if not redirect_target.startswith("/"):
            from backend.platform.runtime_config import cors_origin_for_request

            origin = redirect_target.split("/", 3)[:3]
            normalized_origin = "/".join(origin)
            if not cors_origin_for_request(normalized_origin, handler.services.runtime_config):
                raise AuthenticationError("post_login_redirect_not_allowed")
        handler.send_response(HTTPStatus.FOUND)
        handler._send_common_headers()
        for cookie in cookies:
            handler.send_header("Set-Cookie", cookie)
        handler.send_header("Location", redirect_target)
        handler.send_header("Content-Length", "0")
        handler.end_headers()
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def _issue_session(handler: Any, session: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    user = session.get("user") if isinstance(session.get("user"), dict) else {}
    tenant_ids = tuple(
        _tenant_id_from_label(institution)
        for institution in session.get("institutions", [])
        if str(institution or "").strip()
    )
    grant = handler.services.session_store.issue(
        str(user.get("id") or ""),
        str(session.get("tenant_id") or ""),
        tenant_ids or (str(session.get("tenant_id") or ""),),
        access_ttl_seconds=_access_ttl_seconds(),
        idle_timeout_seconds=_session_ttl_seconds(),
        absolute_timeout_seconds=_absolute_session_ttl_seconds(),
        user_agent_hash=hashlib.sha256(str(handler.headers.get("User-Agent") or "").encode("utf-8")).hexdigest(),
        ip_prefix=_client_ip_prefix(handler),
    )
    token = _token_for_grant(grant)
    response = dict(session)
    response["session_expires_at"] = grant.access_expires_at
    response["session_idle_expires_at"] = grant.idle_expires_at
    response["session_absolute_expires_at"] = grant.absolute_expires_at
    return response, _session_cookies(token, grant.refresh_token, handler.services.runtime_config.is_production)


def _token_for_grant(grant: Any) -> str:
    return make_session_token(
        user_id=grant.user_id,
        tenant_id=grant.primary_tenant_id,
        tenant_ids=grant.tenant_ids,
        ttl_seconds=max(1, grant.access_expires_at - grant.issued_at),
        issued_at=grant.issued_at,
        session_id=grant.access_jti,
        device_session_id=grant.device_session_id,
    )


def _session_cookies(token: str, refresh_token: str, secure: bool) -> list[str]:
    return [
        _cookie("sda_session", token, "/", _access_ttl_seconds(), secure),
        _cookie("sda_refresh", refresh_token, "/api/auth", _absolute_session_ttl_seconds(), secure),
    ]


def _clear_session_cookies(secure: bool) -> list[str]:
    return [
        _cookie("sda_session", "", "/", 0, secure),
        _cookie("sda_refresh", "", "/api/auth", 0, secure),
    ]


def _cookie(name: str, value: str, path: str, max_age: int, secure: bool) -> str:
    parts = [
        f"{name}={value}",
        f"Path={path}",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={max_age}",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def _request_cookies(handler: Any) -> dict[str, str]:
    cookie = SimpleCookie()
    cookie.load(str(handler.headers.get("Cookie") or ""))
    return {name: morsel.value for name, morsel in cookie.items()}


def _session_ttl_seconds() -> int:
    raw = os.getenv("SMART_DATA_AGENT_SESSION_TTL_SECONDS", "1800").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("SMART_DATA_AGENT_SESSION_TTL_SECONDS must be an integer.") from exc
    if value < 60 or value > 24 * 60 * 60:
        raise ValueError("SMART_DATA_AGENT_SESSION_TTL_SECONDS must be between 60 and 86400.")
    return value


def _access_ttl_seconds() -> int:
    return _bounded_timeout("SMART_DATA_AGENT_ACCESS_TTL_SECONDS", 900, 60, 3600)


def _absolute_session_ttl_seconds() -> int:
    value = _bounded_timeout("SMART_DATA_AGENT_SESSION_ABSOLUTE_TTL_SECONDS", 28_800, 300, 604_800)
    if value < _session_ttl_seconds():
        raise ValueError("absolute session timeout must be greater than or equal to idle timeout")
    return value


def _bounded_timeout(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _client_ip_prefix(handler: Any) -> str:
    value = str(handler.client_address[0] if handler.client_address else "")
    if ":" in value:
        return ":".join(value.split(":")[:4])
    return ".".join(value.split(".")[:3])


def _tenant_id_from_label(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("tenant:") or text == "tenant_demo":
        return text
    return f"tenant:{text}"
