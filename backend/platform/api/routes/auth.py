from __future__ import annotations

from http import HTTPStatus
from http.cookies import SimpleCookie
import hashlib
import os
from typing import Any
from urllib.parse import parse_qs
from uuid import uuid4

from backend.authz import SUPER_ADMIN_USER_ID
from backend.platform.api.support import APIRequestContext, send_route_exception
from backend.platform.security import AuthenticationError, make_session_token


def handle_auth_login(handler: Any) -> None:
    payload: dict[str, Any] = {}
    try:
        payload = handler._read_json()
        if handler.services.runtime_config.auth_mode != "development":
            _best_effort_login_survey(handler, None, payload)
            handler._send_json(
                {
                    "error": "external_identity_required",
                    "message": "Strict mode accepts only sessions issued by the configured enterprise identity provider.",
                },
                HTTPStatus.FORBIDDEN,
            )
            return
        email = str(payload.get("email") or "").strip()
        password = str(payload.get("password") or "")
        if not password:
            raise ValueError("invalid_login_credentials")
        tenant_hint = str(payload.get("tenant_id") or payload.get("institution") or "").strip() or None
        try:
            session = handler.services.access_service.login_by_email(email, tenant_hint=tenant_hint, password=password)
        except Exception:
            _best_effort_login_survey(handler, None, payload)
            raise
        survey_submission = _best_effort_login_survey(handler, session, payload)
        response, cookies = _issue_session(handler, session)
        if survey_submission:
            response["survey_submission"] = survey_submission
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


def handle_auth_login_survey(handler: Any) -> None:
    try:
        payload = handler._read_json()
        message = _create_login_survey_if_present(handler, None, payload)
        handler._send_json(
            {"status": "saved" if message else "ignored_empty", "survey_submission": message},
            HTTPStatus.CREATED if message else HTTPStatus.OK,
        )
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def _best_effort_login_survey(
    handler: Any,
    session: dict[str, Any] | None,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        return _create_login_survey_if_present(handler, session, payload)
    except Exception:
        # Survey persistence is additive. It must never change the existing
        # login success/failure behavior or prevent enterprise login fallback.
        return None


def _create_login_survey_if_present(
    handler: Any,
    session: dict[str, Any] | None,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    survey = payload.get("survey")
    if survey is None:
        return None
    if not isinstance(survey, dict):
        raise ValueError("login_survey_invalid")
    needed_metrics = _login_survey_answer(survey.get("needed_metrics") or survey.get("neededMetrics"))
    report_usage = _login_survey_answer(survey.get("report_usage") or survey.get("reportUsage"))
    if not needed_metrics and not report_usage:
        return None
    session_payload = session if isinstance(session, dict) else {}
    user = session_payload.get("user") if isinstance(session_payload.get("user"), dict) else {}
    tenant_id = str(session_payload.get("tenant_id") or "").strip() or _login_survey_tenant_id(handler, payload, survey)
    account_hint = str(payload.get("email") or payload.get("account") or survey.get("account") or "").strip()
    profile = handler.services.access_service.find_profile_by_contact(account_hint) if account_hint else None
    user_id = str(user.get("id") or getattr(profile, "user_id", "") or "").strip()
    if not user_id:
        # Production message-board rows require a provisioned technical author.
        # The visible author remains "登录页访客" and the content/audit detail
        # explicitly marks the identity as unverified.
        user_id = SUPER_ADMIN_USER_ID
    author_name = str(user.get("name") or getattr(profile, "name", "") or "登录页访客").strip()
    if not user_id or not tenant_id:
        raise ValueError("login_survey_identity_required")
    message_id = str(survey.get("message_id") or survey.get("messageId") or f"mb_{uuid4().hex}").strip()
    verified = bool(session)
    trigger = _login_survey_trigger(survey.get("trigger"))
    content = (
        f"你需要什么指标？\n{needed_metrics or '（未填写）'}\n\n"
        f"你平时怎么用报表？\n{report_usage or '（未填写）'}\n\n"
        f"采集方式：{trigger}\n"
        f"身份状态：{'账号已通过登录验证' if verified else '登录前自动保存，填写账号尚未验证'}"
    )
    masked_account = _mask_login_account(account_hint)
    if masked_account:
        content += f"\n填写账号：{masked_account}"
    message = handler.services.message_board_service.create_login_survey(
        tenant_id,
        user_id,
        author_name,
        {
            "message_id": message_id,
            "content": content,
        },
    )
    context = APIRequestContext(user_id=user_id, tenant_id=tenant_id)
    handler._write_audit(
        context,
        "message_board.login_survey.create",
        "message_board_entry",
        message["message_id"],
        {
            "page_key": "login-survey",
            "question_count": int(bool(needed_metrics)) + int(bool(report_usage)),
            "trigger": trigger,
            "verified": verified,
            "storage_surrogate": not bool(user) and profile is None,
        },
    )
    return {"message_id": message["message_id"], "status": message["status"], "verified": verified}


def _login_survey_answer(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) > 1000:
        raise ValueError("login_survey_answer_too_long")
    return text


def _login_survey_tenant_id(handler: Any, payload: dict[str, Any], survey: dict[str, Any]) -> str:
    from backend.platform.api.routes.tenants import _active_tenants

    candidate = str(
        payload.get("tenant_id")
        or payload.get("institution")
        or survey.get("tenant_id")
        or survey.get("tenantId")
        or survey.get("institution")
        or ""
    ).strip()
    for tenant in _active_tenants(handler):
        tenant_id = str(tenant.get("id") or "").strip()
        tenant_name = str(tenant.get("name") or "").strip()
        if candidate in {tenant_id, tenant_name}:
            return tenant_id
    raise ValueError("login_survey_institution_invalid")


def _login_survey_trigger(value: Any) -> str:
    return {
        "login": "点击登录",
        "cancel": "点击取消",
        "pagehide": "关闭或离开登录页",
    }.get(str(value or "login").strip().lower(), "登录页自动保存")


def _mask_login_account(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "@" in text:
        local, domain = text.split("@", 1)
        visible = local[:2]
        return f"{visible}{'*' * max(2, min(6, len(local) - len(visible)))}@{domain}"
    if len(text) <= 4:
        return "*" * len(text)
    return f"{text[:3]}{'*' * max(3, len(text) - 7)}{text[-4:]}"


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
        result = handler.services.access_service.submit_registration_request(payload)
        handler._send_json(result, HTTPStatus.ACCEPTED)
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_auth_password_change(handler: Any) -> None:
    try:
        context = handler._request_context()
        payload = handler._read_json()
        handler.services.access_service.change_password(
            context.user_id,
            str(payload.get("current_password") or payload.get("currentPassword") or ""),
            str(payload.get("new_password") or payload.get("newPassword") or ""),
        )
        handler._write_audit(context, "auth.password.change", "user", context.user_id)
        handler._send_json({"status": "password_changed"})
    except Exception as exc:  # pragma: no cover - HTTP boundary.
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
        session = _session_with_tenant_directory(
            handler,
            handler.services.access_service.session_for_user(
                grant.user_id,
                tenant_hint=grant.primary_tenant_id,
            ),
        )
        token = _token_for_grant(grant, is_super_admin=bool(session.get("is_super_admin")))
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
        session = _session_with_tenant_directory(
            handler,
            handler.services.access_service.session_for_user(context.user_id, tenant_hint=context.tenant_id),
        )
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
    session = _session_with_tenant_directory(handler, session)
    user = session.get("user") if isinstance(session.get("user"), dict) else {}
    tenant_ids = tuple(
        str(item.get("id") or "").strip()
        for item in session.get("tenant_directory", [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
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
    token = _token_for_grant(grant, is_super_admin=bool(session.get("is_super_admin")))
    response = dict(session)
    response["session_expires_at"] = grant.access_expires_at
    response["session_idle_expires_at"] = grant.idle_expires_at
    response["session_absolute_expires_at"] = grant.absolute_expires_at
    return response, _session_cookies(token, grant.refresh_token, handler.services.runtime_config.is_production)


def _session_with_tenant_directory(handler: Any, session: dict[str, Any]) -> dict[str, Any]:
    """Attach the authoritative tenant-code/display-name directory to a session.

    Access assignments intentionally store canonical tenant codes.  UI labels
    come from ``platform_tenants`` (or the deterministic local catalog), never
    from string manipulation of a display name.  Keeping both values in the
    session response gives login, restore, refresh and tenant switching one
    normalization contract.
    """

    from backend.platform.api.routes.tenants import _active_tenants

    user = session.get("user") if isinstance(session.get("user"), dict) else {}
    tenant_roles = user.get("tenantRoles") if isinstance(user.get("tenantRoles"), list) else []
    is_super_admin = bool(session.get("is_super_admin")) or any(
        isinstance(role, dict) and (role.get("tenantId") == "*" or role.get("role") == "超级管理员")
        for role in tenant_roles
    )
    authorized_ids = {
        str(role.get("tenantId") or "").strip()
        for role in tenant_roles
        if isinstance(role, dict) and str(role.get("tenantId") or "").strip() not in {"", "*"}
    }
    current_id = str(session.get("tenant_id") or "").strip()
    if current_id:
        authorized_ids.add(current_id)
    directory = [
        {"id": str(item.get("id") or "").strip(), "name": str(item.get("name") or "").strip()}
        for item in _active_tenants(handler)
        if isinstance(item, dict)
        and str(item.get("id") or "").strip()
        and (is_super_admin or str(item.get("id") or "").strip() in authorized_ids)
    ]
    by_id = {item["id"]: item for item in directory}
    if current_id and current_id not in by_id:
        # Fail closed on authorization, but retain a bounded display fallback
        # for a just-provisioned tenant whose catalog transaction is not yet
        # visible.  The ID remains the backend-issued canonical value.
        fallback_name = str(session.get("institution") or "").strip() or current_id
        directory.append({"id": current_id, "name": fallback_name})
        by_id[current_id] = directory[-1]
    selected = by_id.get(current_id)
    return {
        **session,
        "tenant_id": current_id,
        "institution": str((selected or {}).get("name") or session.get("institution") or ""),
        "institutions": [item["name"] for item in directory],
        "tenant_directory": directory,
    }


def _token_for_grant(grant: Any, *, is_super_admin: bool = False) -> str:
    tenant_ids = grant.tenant_ids
    if is_super_admin:
        tenant_ids = ("*", *tuple(tenant_ids or ()))
    return make_session_token(
        user_id=grant.user_id,
        tenant_id=grant.primary_tenant_id,
        tenant_ids=tenant_ids,
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
