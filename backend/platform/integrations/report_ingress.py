from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.platform.security import AuthenticationError


_CHANNEL_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_VISUAL_TYPES = {"bar", "line", "pie", "table"}
_CHANNEL_LABELS = {
    "workbuddy": "WorkBuddy",
    "feishu": "飞书",
    "dingtalk": "钉钉",
    "wecom": "企业微信",
}


@dataclass(frozen=True)
class ReportIngressBinding:
    binding_id: str
    token: str
    channel: str
    tenant_id: str
    user_id: str
    visibility: str = "private"
    label: str = ""


def resolve_report_ingress_binding(authorization: str | None) -> ReportIngressBinding:
    """Authenticate an external report publisher without accepting caller identity.

    Bindings are deployment-owned secrets.  The client can never select a
    tenant or report owner; those values come only from the matching binding.
    """

    token = _bearer_token(authorization)
    if not token:
        raise AuthenticationError("report_ingress_token_required")
    bindings = _load_bindings()
    if not bindings:
        raise AuthenticationError("report_ingress_not_configured")
    for binding in bindings:
        if hmac.compare_digest(binding.token, token):
            return binding
    raise AuthenticationError("report_ingress_token_invalid")


def build_external_report(payload: dict[str, Any], binding: ReportIngressBinding) -> dict[str, Any]:
    """Normalize one channel result to the existing saved-analysis contract."""

    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    report = payload.get("report") if isinstance(payload.get("report"), dict) else payload
    supplied_channel = _text(source.get("channel"))
    if supplied_channel and supplied_channel != binding.channel:
        raise PermissionError("report_ingress_channel_mismatch")
    source_run_id = _text(source.get("run_id") or source.get("runId"))
    if not source_run_id:
        raise ValueError("report_ingress_source_run_id_required")

    source_report_id = _text(source.get("report_id") or source.get("reportId")) or source_run_id
    report_id = _stable_report_id(binding, source_run_id, source_report_id)
    title = _text(report.get("title")) or f"{binding.label}分析报告"
    query = _text(report.get("query") or report.get("question")) or title
    visual_types = report.get("visualTypes") if isinstance(report.get("visualTypes"), dict) else report.get("visual_types")
    visual_types = visual_types if isinstance(visual_types, dict) else {}
    return {
        "id": report_id,
        "title": title[:500],
        "query": query[:4000],
        "plan": _text(report.get("plan") or report.get("methodology"))[:8000],
        "summary": _text(report.get("summary") or report.get("conclusion"))[:20_000],
        "visualTypes": {
            "primary": _visual_type(visual_types.get("primary"), "bar"),
            "secondary": _visual_type(visual_types.get("secondary"), "table"),
        },
        "savedAt": _text(report.get("savedAt") or report.get("saved_at")) or _utc_now(),
        "analysisTaskId": "",
        "visibility": binding.visibility,
        "rows": _rows(report.get("rows") or report.get("data")),
        "source": {
            "channel": binding.channel,
            "label": binding.label,
            "bindingId": binding.binding_id,
            "runId": source_run_id,
            "reportId": source_report_id,
            "url": _text(source.get("url"))[:2000],
        },
    }


def _load_bindings() -> list[ReportIngressBinding]:
    raw = ""
    secret_file = os.getenv("SMART_DATA_AGENT_REPORT_INGRESS_BINDINGS_FILE", "").strip()
    if secret_file:
        path = Path(secret_file).expanduser()
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise AuthenticationError("report_ingress_binding_file_unavailable") from exc
    else:
        raw = os.getenv("SMART_DATA_AGENT_REPORT_INGRESS_BINDINGS_JSON", "")
    if not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AuthenticationError("report_ingress_binding_config_invalid") from exc
    entries = parsed.get("bindings") if isinstance(parsed, dict) else parsed
    if not isinstance(entries, list):
        raise AuthenticationError("report_ingress_binding_config_invalid")
    bindings: list[ReportIngressBinding] = []
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            raise AuthenticationError("report_ingress_binding_config_invalid")
        channel = _channel(_text(item.get("channel")))
        token = _text(item.get("token"))
        tenant_id = _text(item.get("tenant_id"))
        user_id = _text(item.get("user_id"))
        binding_id = _text(item.get("id")) or f"{channel}-{index + 1}"
        visibility = _text(item.get("visibility")) or "private"
        if not token or not tenant_id or not user_id or visibility not in {"private", "tenant"}:
            raise AuthenticationError("report_ingress_binding_config_invalid")
        bindings.append(
            ReportIngressBinding(
                binding_id=binding_id[:120],
                token=token,
                channel=channel,
                tenant_id=tenant_id,
                user_id=user_id,
                visibility=visibility,
                label=_text(item.get("label"))[:120] or _CHANNEL_LABELS.get(channel, channel),
            )
        )
    return bindings


def _bearer_token(authorization: str | None) -> str:
    value = _text(authorization)
    prefix = "Bearer "
    return value[len(prefix):].strip() if value.lower().startswith(prefix.lower()) else ""


def _channel(value: str) -> str:
    if not _CHANNEL_RE.fullmatch(value):
        raise AuthenticationError("report_ingress_binding_config_invalid")
    return value


def _stable_report_id(binding: ReportIngressBinding, run_id: str, source_report_id: str) -> str:
    identity = f"{binding.binding_id}:{binding.channel}:{run_id}:{source_report_id}".encode("utf-8")
    return f"external_{binding.channel}_{hashlib.sha256(identity).hexdigest()[:28]}"


def _visual_type(value: Any, fallback: str) -> str:
    candidate = _text(value).lower()
    return candidate if candidate in _VISUAL_TYPES else fallback


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for row in value[:50_000]:
        if isinstance(row, dict):
            rows.append({str(key)[:200]: cell for key, cell in row.items()})
    return rows


def _text(value: Any) -> str:
    return str(value or "").strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
