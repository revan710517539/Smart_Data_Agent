from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib import error, parse, request


BRIDGE_CONNECTOR_SCHEMA = "bridge_connector_registry_v1"
BRIDGE_CONTRACT_VERSION = "1.0"
BRIDGE_MODULES = ("analysis_sync", "configuration", "read", "learning")
BRIDGE_CHANNELS = frozenset({"workbuddy", "codex", "qwork"})
MAX_CONNECTOR_CONFIG_BYTES = 512 * 1024
MAX_CONNECTOR_RESPONSE_BYTES = 2 * 1024 * 1024
_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")


class BridgeConnectorRegistry:
    """Deployment-owned connector catalog with immediate file-based discovery.

    The catalog deliberately contains no credential values. Existing clients
    read the public manifest on every task, so adding an adapter in the server
    config never requires reinstalling the WorkBuddy, Codex or QWork bridge.
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        configured = str(config_path or os.getenv("SMART_DATA_AGENT_BRIDGE_CONNECTORS_FILE") or "").strip()
        self.config_path = Path(configured).expanduser() if configured else None

    def connectors(self) -> dict[str, dict[str, Any]]:
        result = {"sda": _builtin_sda_connector()}
        if self.config_path is None:
            return result
        try:
            if self.config_path.stat().st_size > MAX_CONNECTOR_CONFIG_BYTES:
                raise ValueError("bridge_connector_registry_too_large")
            raw = self.config_path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise ValueError("bridge_connector_registry_unavailable") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("bridge_connector_registry_invalid_json") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != BRIDGE_CONNECTOR_SCHEMA:
            raise ValueError("bridge_connector_registry_schema_invalid")
        items = payload.get("connectors")
        if not isinstance(items, list) or len(items) > 100:
            raise ValueError("bridge_connector_registry_entries_invalid")
        for item in items:
            connector = _validate_http_connector(item)
            connector_id = connector["id"]
            if connector_id == "sda" or connector_id in result:
                raise ValueError("bridge_connector_registry_duplicate_id")
            if connector["enabled"]:
                result[connector_id] = connector
        return result

    def public_manifest(self, channel: str) -> dict[str, Any]:
        normalized_channel = _channel(channel)
        systems = [
            _public_connector(connector)
            for connector in self.connectors().values()
            if normalized_channel in connector["allowed_channels"]
        ]
        return {
            "schema_version": "bridge_manifest_v1",
            "contract_version": BRIDGE_CONTRACT_VERSION,
            "refresh_policy": "discover_on_each_task",
            "client_reinstall_required_for_new_system": False,
            "modules": list(BRIDGE_MODULES),
            "systems": sorted(systems, key=lambda item: (item["label"].casefold(), item["id"])),
        }

    def require(self, system_id: str, channel: str) -> dict[str, Any]:
        normalized_id = str(system_id or "").strip().lower()
        connector = self.connectors().get(normalized_id)
        if connector is None or _channel(channel) not in connector["allowed_channels"]:
            raise PermissionError("bridge_system_unavailable")
        return connector


def invoke_http_connector(
    connector: dict[str, Any],
    module: str,
    *,
    binding: Any,
    payload: dict[str, Any],
    action: str = "",
) -> dict[str, Any]:
    """Call one allowlisted adapter endpoint with server-authored identity."""

    if connector.get("adapter") != "http_json":
        raise ValueError("bridge_connector_adapter_invalid")
    if module not in BRIDGE_MODULES:
        raise ValueError("bridge_module_invalid")
    modules = connector["modules"]
    endpoint_spec: dict[str, Any]
    if module == "configuration":
        normalized_action = str(action or "").strip()
        endpoint_spec = modules[module]["actions"].get(normalized_action)
        if endpoint_spec is None:
            raise PermissionError("bridge_configuration_action_not_allowed")
    else:
        endpoint_spec = modules[module]
    operation_id = str(payload.get("operation_id") or payload.get("operationId") or "").strip()
    if module in {"analysis_sync", "configuration", "learning"} and not operation_id:
        raise ValueError("bridge_operation_id_required")
    url = connector["base_url"] + endpoint_spec["path"]
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "smart-data-agent-universal-bridge/1",
        "X-Bridge-Contract-Version": BRIDGE_CONTRACT_VERSION,
    }
    auth = connector["auth"]
    if auth["type"] == "bearer_env":
        token = str(os.getenv(auth["environment"]) or "").strip()
        if not token:
            raise RuntimeError("bridge_connector_secret_unavailable")
        headers["Authorization"] = f"Bearer {token}"
    request_payload = {
        "schema_version": "bridge_request_v1",
        "contract_version": BRIDGE_CONTRACT_VERSION,
        "system_id": connector["id"],
        "module": module,
        "action": str(action or ""),
        "operation_id": operation_id,
        "identity": {
            "tenant_id": binding.tenant_id,
            "user_id": binding.user_id,
            "channel": binding.channel,
            "binding_id": binding.binding_id,
        },
        "input": payload.get("input") if isinstance(payload.get("input"), dict) else payload,
    }
    req = request.Request(
        url,
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    try:
        with request.urlopen(req, timeout=connector["timeout_seconds"]) as response:
            body = response.read(MAX_CONNECTOR_RESPONSE_BYTES + 1)
    except error.HTTPError as exc:
        raise RuntimeError(f"bridge_connector_rejected:http_{exc.code}") from exc
    except error.URLError as exc:
        raise RuntimeError("bridge_connector_unreachable") from exc
    if len(body) > MAX_CONNECTOR_RESPONSE_BYTES:
        raise ValueError("bridge_connector_response_too_large")
    try:
        result = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("bridge_connector_response_invalid") from exc
    if not isinstance(result, dict):
        raise ValueError("bridge_connector_response_invalid")
    return result


def _builtin_sda_connector() -> dict[str, Any]:
    return {
        "id": "sda",
        "label": "Smart Data Agent",
        "description": "受治理的数据、报告、分析配置、记忆与 Skill 闭环。",
        "aliases": ["smart data agent", "smart_data_agent", "智能数据分析", "数据智能体"],
        "adapter": "builtin_sda",
        "enabled": True,
        "allowed_channels": sorted(BRIDGE_CHANNELS),
        "modules": {
            "analysis_sync": {"supported": True},
            "configuration": {"actions": {"analysis_shortcut.upsert": {"supported": True}}},
            "read": {"resources": ["authorized_context", "raw_table.rows"]},
            "learning": {"supported": True, "activation": "review_only"},
        },
    }


def _validate_http_connector(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("bridge_connector_invalid")
    forbidden_secret_keys = {"token", "secret", "api_key", "apikey", "password", "authorization"}
    if forbidden_secret_keys.intersection({str(key).strip().lower() for key in value}):
        raise ValueError("bridge_connector_inline_secret_forbidden")
    connector_id = str(value.get("id") or "").strip().lower()
    if not _ID_RE.fullmatch(connector_id):
        raise ValueError("bridge_connector_id_invalid")
    label = str(value.get("label") or "").strip()[:160]
    if not label:
        raise ValueError("bridge_connector_label_required")
    if str(value.get("adapter") or "") != "http_json":
        raise ValueError("bridge_connector_adapter_invalid")
    base_url = str(value.get("base_url") or "").strip().rstrip("/")
    parsed = parse.urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.query or parsed.fragment:
        raise ValueError("bridge_connector_base_url_invalid")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("bridge_connector_https_required")
    channels = value.get("allowed_channels")
    if not isinstance(channels, list) or not channels:
        raise ValueError("bridge_connector_channels_required")
    allowed_channels = sorted({_channel(item) for item in channels})
    modules = value.get("modules")
    if not isinstance(modules, dict) or set(modules) != set(BRIDGE_MODULES):
        raise ValueError("bridge_connector_four_modules_required")
    normalized_modules = {
        "analysis_sync": _endpoint_spec(modules["analysis_sync"]),
        "read": _endpoint_spec(modules["read"]),
        "learning": _endpoint_spec(modules["learning"]),
    }
    configuration = modules["configuration"]
    actions = configuration.get("actions") if isinstance(configuration, dict) else None
    if not isinstance(actions, dict) or not actions or len(actions) > 100:
        raise ValueError("bridge_connector_configuration_actions_required")
    normalized_actions: dict[str, dict[str, Any]] = {}
    for action, spec in actions.items():
        action_name = str(action or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{1,127}", action_name):
            raise ValueError("bridge_connector_action_invalid")
        normalized_actions[action_name] = _endpoint_spec(spec)
    normalized_modules["configuration"] = {"actions": normalized_actions}
    auth = value.get("auth")
    if not isinstance(auth, dict) or auth.get("type") not in {"bearer_env", "none"}:
        raise ValueError("bridge_connector_auth_invalid")
    if set(auth) - {"type", "environment"}:
        raise ValueError("bridge_connector_inline_secret_forbidden")
    normalized_auth = {"type": str(auth["type"])}
    if normalized_auth["type"] == "bearer_env":
        environment = str(auth.get("environment") or "").strip()
        if not _ENV_RE.fullmatch(environment):
            raise ValueError("bridge_connector_auth_environment_invalid")
        normalized_auth["environment"] = environment
    elif parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("bridge_connector_auth_required")
    aliases = [str(item).strip()[:120] for item in value.get("aliases", []) if str(item).strip()][:20] if isinstance(value.get("aliases"), list) else []
    return {
        "id": connector_id,
        "label": label,
        "description": str(value.get("description") or "").strip()[:1000],
        "aliases": aliases,
        "adapter": "http_json",
        "base_url": base_url,
        "auth": normalized_auth,
        "enabled": value.get("enabled") is not False,
        "allowed_channels": allowed_channels,
        "timeout_seconds": max(1, min(int(value.get("timeout_seconds") or 20), 30)),
        "modules": normalized_modules,
    }


def _endpoint_spec(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("bridge_connector_endpoint_invalid")
    path = str(value.get("path") or "").strip()
    if not path.startswith("/") or path.startswith("//") or "?" in path or "#" in path:
        raise ValueError("bridge_connector_endpoint_path_invalid")
    return {"path": path}


def _public_connector(connector: dict[str, Any]) -> dict[str, Any]:
    modules = connector["modules"]
    configuration_actions = sorted(modules["configuration"]["actions"])
    read_resources = list(modules["read"].get("resources") or ["connector_defined"])
    return {
        "id": connector["id"],
        "label": connector["label"],
        "description": connector["description"],
        "aliases": connector["aliases"],
        "modules": {
            "analysis_sync": {"supported": True},
            "configuration": {"supported": True, "actions": configuration_actions},
            "read": {"supported": True, "resources": read_resources},
            "learning": {"supported": True, "activation": "review_only"},
        },
    }


def _channel(value: Any) -> str:
    channel = str(value or "").strip().lower()
    if channel not in BRIDGE_CHANNELS:
        raise PermissionError("bridge_channel_unsupported")
    return channel
