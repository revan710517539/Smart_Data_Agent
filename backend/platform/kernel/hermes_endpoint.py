from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


class HermesEndpointError(RuntimeError):
    """Raised when a Hermes draft backend is misconfigured for this process."""


@dataclass(frozen=True)
class HermesEndpoint:
    """Swappable Hermes attachment. Local and server differ only by env.

    Local example::

        SMART_DATA_AGENT_HERMES_MODE=cli
        SMART_DATA_AGENT_HERMES_BIN=hermes
        SMART_DATA_AGENT_HERMES_HOME=${HOME}/.hermes

    Server example::

        SMART_DATA_AGENT_HERMES_MODE=cli
        SMART_DATA_AGENT_HERMES_BIN=/usr/local/bin/hermes
        SMART_DATA_AGENT_HERMES_HOME=/opt/hermes

    Or HTTP on either side::

        SMART_DATA_AGENT_HERMES_MODE=http
        SMART_DATA_AGENT_HERMES_ENDPOINT=http://localhost:<managed-port>
    """

    mode: str
    binary: str
    home: str
    profile: str
    endpoint: str
    timeout_seconds: int
    extra_args: tuple[str, ...]

    @property
    def enabled(self) -> bool:
        return self.mode in {"cli", "http"}

    def public_status(self) -> dict[str, object]:
        return {
            "ready": True,
            "mode": self.mode,
            "configured": self.enabled,
            "binary_configured": bool(self.binary),
            "home_configured": bool(self.home),
            "endpoint_configured": bool(self.endpoint),
            "profile": self.profile,
            "timeout_seconds": self.timeout_seconds,
        }


def load_hermes_endpoint(environ: dict[str, str] | None = None) -> HermesEndpoint:
    env = environ if environ is not None else os.environ
    sda_env = str(env.get("SMART_DATA_AGENT_ENV", "development") or "development").strip().lower()
    requested = str(env.get("SMART_DATA_AGENT_HERMES_MODE", "") or "").strip().lower()
    endpoint = str(env.get("SMART_DATA_AGENT_HERMES_ENDPOINT", "") or "").strip().rstrip("/")
    binary = str(env.get("SMART_DATA_AGENT_HERMES_BIN", "") or "").strip()
    home = str(env.get("SMART_DATA_AGENT_HERMES_HOME", "") or "").strip()
    profile = str(env.get("SMART_DATA_AGENT_HERMES_PROFILE", "") or "").strip() or "default"
    timeout_seconds = _bounded_int(env.get("SMART_DATA_AGENT_HERMES_TIMEOUT_SECONDS"), 15, 5, 60)
    extra = tuple(
        part.strip()
        for part in str(env.get("SMART_DATA_AGENT_HERMES_EXTRA_ARGS", "") or "").split()
        if part.strip()
    )
    # auto/empty stays off. Local and server Hermes are attached only when
    # SMART_DATA_AGENT_HERMES_MODE is set to cli or http, so a machine with
    # a personal Hermes install cannot leak into tests or production by PATH.
    if requested in {"", "auto"}:
        mode = "off"
    else:
        mode = requested
    if mode not in {"off", "cli", "http"}:
        raise HermesEndpointError(f"unsupported_hermes_mode:{mode}")
    if mode == "http":
        if not endpoint:
            raise HermesEndpointError("SMART_DATA_AGENT_HERMES_ENDPOINT is required for http mode")
        if sda_env == "production" and not endpoint.startswith("https://") and not _loopback(endpoint):
            raise HermesEndpointError("production Hermes HTTP endpoint must use https")
    if mode == "cli":
        resolved_binary = binary or shutil.which("hermes") or ""
        if not resolved_binary:
            raise HermesEndpointError("SMART_DATA_AGENT_HERMES_BIN or hermes on PATH is required for cli mode")
        if sda_env in {"staging", "production"} and not home:
            raise HermesEndpointError("SMART_DATA_AGENT_HERMES_HOME is required for cli mode outside development")
        binary = resolved_binary
    return HermesEndpoint(
        mode=mode,
        binary=binary,
        home=str(Path(home).expanduser()) if home else "",
        profile=profile,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        extra_args=extra,
    )


def _loopback(url: str) -> bool:
    lowered = url.lower()
    return "://127.0.0.1" in lowered or "://localhost" in lowered or "://[::1]" in lowered


def _bounded_int(value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value or default))
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))
