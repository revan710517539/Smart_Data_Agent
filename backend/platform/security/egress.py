from __future__ import annotations

import ipaddress
import os
import socket
import ssl
from typing import Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

from websocket import create_connection as _websocket_create_connection


class EgressPolicyError(ValueError):
    """Raised when an outbound URL violates the server egress policy."""


def classify_egress_policy_error(exc: EgressPolicyError) -> tuple[str, str, bool]:
    """Map an egress rejection to a stable code and operator-facing message."""

    detail = str(exc).strip()
    if "cannot be resolved" in detail:
        return (
            "dns_resolution_failed",
            "地址域名无法解析：企业中转站需要后端走本机代理（Clash HTTPS_PROXY）或企业 DNS/VPN。",
            False,
        )
    if "has no resolved address" in detail:
        return (
            "dns_resolution_failed",
            "运行 Smart Data Agent 后端的服务器未获得该地址的解析结果。请检查企业 DNS/VPN 或网关地址后重试。",
            False,
        )
    if "scheme must be" in detail:
        return "egress_policy_rejected", "地址协议不符合服务端出站安全策略，请使用允许的协议。", False
    if "blocked address" in detail:
        return (
            "egress_policy_rejected",
            "地址解析到内网或本机代理假 IP，已被服务端出站安全策略拦截。",
            False,
        )
    if "not allowlisted" in detail:
        return "egress_policy_rejected", "地址不在服务端出站白名单内。", False
    return "egress_policy_rejected", "地址不符合服务端出站安全策略。", False


def validate_outbound_url(
    url: str,
    *,
    allowed_schemes: tuple[str, ...] = ("https",),
    private_host_exceptions: tuple[str, ...] = (),
) -> str:
    parsed = urlparse(str(url or "").strip())
    scheme = parsed.scheme.lower()
    if scheme not in allowed_schemes:
        raise EgressPolicyError(f"Outbound URL scheme must be one of: {', '.join(allowed_schemes)}")
    if not parsed.hostname or parsed.username or parsed.password:
        raise EgressPolicyError("Outbound URL must have a hostname and must not contain user info.")
    host = parsed.hostname.rstrip(".").lower()
    allowlist = _host_patterns("SMART_DATA_AGENT_EGRESS_ALLOWED_HOSTS")
    private_allowlist = _host_patterns("SMART_DATA_AGENT_EGRESS_PRIVATE_HOSTS")
    direct_allowlist = _host_patterns("SMART_DATA_AGENT_EGRESS_DIRECT_HOSTS")
    environment = os.getenv("SMART_DATA_AGENT_ENV", "development").strip().lower()
    if environment in {"staging", "production"} and not allowlist:
        raise EgressPolicyError("Production egress requires SMART_DATA_AGENT_EGRESS_ALLOWED_HOSTS.")
    if allowlist and not _host_matches(host, allowlist):
        raise EgressPolicyError(f"Outbound host is not allowlisted: {host}")
    allow_private = _host_matches(host, private_allowlist) or _host_matches(host, private_host_exceptions)
    if _egress_proxy_url() and not _is_ip_literal(host) and not _host_matches(host, direct_allowlist):
        return parsed.geturl()
    port = parsed.port or (443 if scheme in {"https", "wss"} else 80)
    try:
        addresses = _resolve_addresses(host, port)
    except OSError as exc:
        raise EgressPolicyError(f"Outbound hostname cannot be resolved: {host}") from exc
    if not addresses:
        raise EgressPolicyError(f"Outbound hostname has no resolved address: {host}")
    if not allow_private:
        blocked = [str(address) for address in addresses if not _is_public_address(address)]
        if blocked:
            raise EgressPolicyError(f"Outbound host resolves to a blocked address: {', '.join(blocked)}")
    return parsed.geturl()


def create_governed_websocket_connection(
    url: str,
    *,
    timeout: float,
    header: list[str],
    ca_certs: str | None = None,
):
    """Open a WebSocket without inheriting an unmanaged process proxy."""

    validated = validate_outbound_url(url, allowed_schemes=("ws", "wss"))
    options: dict[str, object] = {
        "timeout": timeout,
        "header": header,
        "sslopt": {
            "cert_reqs": ssl.CERT_REQUIRED,
            **({"ca_certs": ca_certs} if ca_certs else {}),
        },
    }
    target_host = (urlparse(validated).hostname or "").rstrip(".").lower()
    direct_allowlist = _host_patterns("SMART_DATA_AGENT_EGRESS_DIRECT_HOSTS")
    proxy = "" if _host_matches(target_host, direct_allowlist) else _egress_proxy_url()
    if proxy:
        proxy_url = urlparse(proxy)
        if proxy_url.scheme != "http":
            raise EgressPolicyError("WebSocket egress proxy must use http CONNECT.")
        options.update(
            {
                "http_proxy_host": proxy_url.hostname,
                "http_proxy_port": proxy_url.port or 80,
                "proxy_type": "http",
            }
        )
        if proxy_url.username:
            options["http_proxy_auth"] = (proxy_url.username, proxy_url.password or "")
    else:
        # websocket-client otherwise reads lowercase/uppercase proxy variables
        # implicitly. A pre-connected socket makes direct transport explicit.
        options["socket"] = _open_direct_websocket_socket(
            validated,
            timeout=timeout,
            ca_certs=ca_certs,
        )
    return _websocket_create_connection(validated, **options)


def safe_urlopen(
    request: Request,
    *,
    timeout: float,
    context: ssl.SSLContext,
    allowed_schemes: tuple[str, ...] = ("https",),
    private_host_exceptions: tuple[str, ...] = (),
):
    validate_outbound_url(
        request.full_url,
        allowed_schemes=allowed_schemes,
        private_host_exceptions=private_host_exceptions,
    )
    handlers: list[object] = []
    proxy = _egress_proxy_url()
    if proxy:
        handlers.append(ProxyHandler({"http": proxy, "https": proxy}))
    handlers.extend(
        [
            _ValidatingRedirectHandler(allowed_schemes, private_host_exceptions),
            HTTPSHandler(context=context),
        ]
    )
    opener = build_opener(*handlers)
    return opener.open(request, timeout=timeout)


def _open_direct_websocket_socket(url: str, *, timeout: float, ca_certs: str | None):
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    context = ssl.create_default_context(cafile=ca_certs or None)
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    # Prefer IPv4 for current Aliyun speech endpoints, while retaining IPv6 as
    # a real fallback. A successful TCP connection can still fail during TLS;
    # retrying only TCP (socket.create_connection) was therefore insufficient.
    addresses.sort(key=lambda item: 0 if item[0] == socket.AF_INET else 1)
    last_error: BaseException | None = None
    for family, socktype, proto, _canonname, sockaddr in addresses:
        raw_socket = socket.socket(family, socktype, proto)
        raw_socket.settimeout(timeout)
        try:
            raw_socket.connect(sockaddr)
            if parsed.scheme == "ws":
                return raw_socket
            return context.wrap_socket(raw_socket, server_hostname=host)
        except BaseException as exc:
            last_error = exc
            raw_socket.close()
    if last_error is not None:
        raise last_error
    raise OSError(f"WebSocket hostname has no resolved address: {host}")


class _ValidatingRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_schemes: tuple[str, ...], private_host_exceptions: tuple[str, ...] = ()) -> None:
        super().__init__()
        self._allowed_schemes = allowed_schemes
        self._private_host_exceptions = private_host_exceptions

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        resolved = urljoin(req.full_url, newurl)
        validate_outbound_url(
            resolved,
            allowed_schemes=self._allowed_schemes,
            private_host_exceptions=self._private_host_exceptions,
        )
        current = urlparse(req.full_url)
        target = urlparse(resolved)
        if (current.scheme.lower(), current.hostname, current.port) != (
            target.scheme.lower(),
            target.hostname,
            target.port,
        ):
            raise EgressPolicyError("Credentialed outbound requests cannot redirect to another origin.")
        return super().redirect_request(req, fp, code, msg, headers, resolved)


def _resolve_addresses(host: str, port: int) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return {ipaddress.ip_address(host)}
    except ValueError:
        pass
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for family, _socktype, _proto, _canonname, sockaddr in socket.getaddrinfo(
        host,
        port,
        type=socket.SOCK_STREAM,
    ):
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        addresses.add(ipaddress.ip_address(sockaddr[0]))
    return addresses


def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(address.is_global and not address.is_multicast and not address.is_unspecified)


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _egress_proxy_url() -> str:
    raw = (os.getenv("SMART_DATA_AGENT_EGRESS_PROXY") or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    return parsed.geturl()


def _host_patterns(env_name: str) -> tuple[str, ...]:
    return tuple(
        value.strip().rstrip(".").lower()
        for value in os.getenv(env_name, "").split(",")
        if value.strip()
    )


def _host_matches(host: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        if pattern.startswith("*.") and host.endswith(pattern[1:]) and host != pattern[2:]:
            return True
        if host == pattern:
            return True
    return False
