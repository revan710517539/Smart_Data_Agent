from __future__ import annotations

import ipaddress
import os
import socket
import ssl
from typing import Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


class EgressPolicyError(ValueError):
    """Raised when an outbound URL violates the server egress policy."""


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
    environment = os.getenv("SMART_DATA_AGENT_ENV", "development").strip().lower()
    if environment in {"staging", "production"} and not allowlist:
        raise EgressPolicyError("Production egress requires SMART_DATA_AGENT_EGRESS_ALLOWED_HOSTS.")
    if allowlist and not _host_matches(host, allowlist):
        raise EgressPolicyError(f"Outbound host is not allowlisted: {host}")
    allow_private = _host_matches(host, private_allowlist) or _host_matches(host, private_host_exceptions)
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
    opener = build_opener(_ValidatingRedirectHandler(allowed_schemes, private_host_exceptions), HTTPSHandler(context=context))
    return opener.open(request, timeout=timeout)


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
