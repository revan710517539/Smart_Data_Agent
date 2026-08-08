"""Minimal 360Teams self-message provider used by metric subscriptions.

The provider intentionally exposes only the device-code flow and the
``send-to-self`` endpoint.  The browser never receives the resulting gateway
token; it is encrypted as part of the owned subscription channel config.
"""

from __future__ import annotations

import json
import platform
from typing import Any
from urllib.request import Request

import certifi

from backend.platform.security import safe_urlopen, validate_outbound_url


TEAMS_DEVICE_CODE_URL = "https://sk.360teams.com/api/token/agent/device/code/create"
TEAMS_DEVICE_TOKEN_URL = "https://sk.360teams.com/api/token/agent/device/code/token"
TEAMS_SELF_MESSAGE_URL = "https://sk.360teams.com/api/rce-app/publish/private/message/self"
TEAMS_PRIVATE_EGRESS_HOSTS = ("sk.360teams.com",)
TEAMS_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class TeamsProviderError(RuntimeError):
    pass


def start_device_authorization() -> dict[str, str]:
    payload = _request_json(
        TEAMS_DEVICE_CODE_URL,
        {"name": "Smart Data Agent", "model": "metric-subscription", "os": f"{platform.system()} {platform.release()}"},
        authorization=None,
    )
    data = _data(payload)
    device_code = _required(data.get("deviceCode"), "teams_device_code_missing")
    sso_url = _required(data.get("ssoUrl"), "teams_sso_url_missing")
    return {"device_code": device_code, "sso_url": sso_url}


def complete_device_authorization(device_code: str) -> str | None:
    payload = _request_json(
        TEAMS_DEVICE_TOKEN_URL,
        {"deviceCode": _required(device_code, "teams_device_code_required")},
        authorization=None,
        allow_pending=True,
    )
    token = str(_data(payload).get("token") or "").strip()
    if not token:
        return None
    try:
        token.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise TeamsProviderError("teams_gateway_token_invalid") from exc
    return token


def send_markdown_to_self(access_token: str, title: str, text: str) -> str:
    clean_title = " ".join(str(title or "").split())[:50]
    clean_text = str(text or "").strip()[:5000]
    if not clean_text:
        raise TeamsProviderError("teams_message_content_required")
    payload = _request_json(
        TEAMS_SELF_MESSAGE_URL,
        {"msgType": "markdown", "markdown": {"title": clean_title, "text": clean_text}},
        authorization=_required(access_token, "teams_access_token_required"),
    )
    data = _data(payload)
    return str(data.get("messageId") or data.get("id") or "teams-self-accepted")[:300]


def _request_json(
    url: str,
    body: dict[str, Any],
    *,
    authorization: str | None,
    allow_pending: bool = False,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "User-Agent": TEAMS_BROWSER_USER_AGENT}
    if authorization:
        headers["Authorization"] = authorization
    request = Request(
        validate_outbound_url(url, private_host_exceptions=TEAMS_PRIVATE_EGRESS_HOSTS),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with safe_urlopen(
            request,
            timeout=15,
            context=__import__("ssl").create_default_context(cafile=certifi.where()),
            private_host_exceptions=TEAMS_PRIVATE_EGRESS_HOSTS,
        ) as response:
            if not 200 <= int(response.status) < 300:
                raise TeamsProviderError(f"teams_provider_http_{int(response.status)}")
            raw = response.read(1024 * 1024)
    except TeamsProviderError:
        raise
    except Exception as exc:
        raise TeamsProviderError("teams_provider_unavailable") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise TeamsProviderError("teams_provider_response_invalid") from exc
    if not isinstance(payload, dict):
        raise TeamsProviderError("teams_provider_response_invalid")
    if payload.get("code") not in (None, 0) and not allow_pending:
        raise TeamsProviderError(f"teams_provider_business_{str(payload.get('code'))[:24]}")
    return payload


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("data")
    return value if isinstance(value, dict) else payload


def _required(value: Any, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise TeamsProviderError(code)
    return text
