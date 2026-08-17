#!/usr/bin/env python3
"""Bridge governed external analysis clients to Smart Data Agent.

This file intentionally ships inside the plugin.  WorkBuddy copies installed
plugins into a versioned cache, where references to project files outside the
plugin root are unavailable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import secrets
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any
from urllib import error, parse, request


def _default_config_path() -> Path:
    if sys.platform == "win32":
        appdata = os.getenv("APPDATA")
        return Path(appdata) / "smart-data-agent" / "report-cli.json" if appdata else Path.home() / "AppData" / "Roaming" / "smart-data-agent" / "report-cli.json"
    return Path.home() / ".config" / "smart-data-agent" / "report-cli.json"


def _windows_token_path(keychain_service: str = "smart-data-agent-report-token") -> Path:
    appdata = os.getenv("APPDATA")
    suffix = ""
    normalized_service = str(keychain_service or "").strip().lower()
    if normalized_service.startswith("smart-data-agent-bridge-"):
        channel = normalized_service.removeprefix("smart-data-agent-bridge-")
        if channel in {"workbuddy", "codex", "qwork"}:
            suffix = f"-{channel}"
    filename = f"report-cli{suffix}.token"
    return Path(appdata) / "smart-data-agent" / filename if appdata else Path.home() / "AppData" / "Roaming" / "smart-data-agent" / filename


DEFAULT_CONFIG = _default_config_path()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="SDA", description="Publish an external analysis report to Smart Data Agent.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    publish = subcommands.add_parser("publish", help="Publish one channel report.")
    publish.add_argument("--channel", required=True, help="Registered channel ID, for example workbuddy.")
    source = publish.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="Path to the channel report JSON file.")
    source.add_argument("--stdin", action="store_true", help="Read the channel report JSON from stdin.")
    publish.add_argument("--endpoint", help="Remote Smart Data Agent base URL or full ingress URL.")
    publish.add_argument("--token-env", default="SMART_DATA_AGENT_REPORT_TOKEN", help="Environment variable containing the ingress token.")
    publish.add_argument("--token-keychain-service", default="smart-data-agent-report-token", help="macOS Keychain service used when --token-env is absent.")
    publish.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help=f"Optional non-secret config file (default: {DEFAULT_CONFIG}).")
    publish.add_argument("--timeout", type=float, default=20, help="HTTP timeout in seconds.")
    publish.add_argument("--dry-run", action="store_true", help="Validate the package and print only safe metadata.")
    publish.add_argument("--json", action="store_true", help="Print the server response as JSON.")
    connect = subcommands.add_parser("connect", help="Authorize this device once in the SDA browser and store the channel token securely.")
    connect.add_argument("--channel", required=True, choices=("workbuddy", "codex", "qwork"), help="Bridge channel to authorize.")
    connect.add_argument("--endpoint", help="Remote Smart Data Agent base URL.")
    connect.add_argument("--app-url", help="Smart Data Agent browser URL; defaults to config app_url or the API origin.")
    connect.add_argument("--token-keychain-service", default="", help="macOS Keychain service or Windows channel token slot.")
    connect.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help=f"Optional non-secret config file (default: {DEFAULT_CONFIG}).")
    connect.add_argument("--device-name", default="", help="Device label shown on the SDA approval page.")
    connect.add_argument("--no-open", action="store_true", help="Print but do not open the browser approval URL.")
    connect.add_argument("--timeout", type=float, default=600, help="Maximum seconds to wait for the approval click.")
    connect.add_argument("--json", action="store_true", help="Print safe binding metadata as JSON.")
    bridge = subcommands.add_parser("bridge", help="Read approved SDA data and return bounded analysis evidence.")
    bridge.add_argument("--channel", required=True, choices=("workbuddy", "codex", "qwork"), help="Token-bound external analysis channel.")
    bridge_subcommands = bridge.add_subparsers(dest="bridge_command", required=True)
    _add_bridge_commands(bridge_subcommands, "Bridge")
    workbuddy = subcommands.add_parser("workbuddy", help="Compatibility alias for `bridge --channel workbuddy`.")
    workbuddy_subcommands = workbuddy.add_subparsers(dest="workbuddy_command", required=True)
    _add_bridge_commands(workbuddy_subcommands, "WorkBuddy")
    args = parser.parse_args(argv)
    if args.command == "publish":
        return _publish(args)
    if args.command == "connect":
        return _connect(args)
    if args.command == "bridge":
        return _bridge(args, args.channel, args.bridge_command)
    return _bridge(args, "workbuddy", args.workbuddy_command) if args.command == "workbuddy" else 2


def _add_bridge_commands(subcommands: Any, client_label: str) -> None:
    def common(command: Any) -> None:
        command.add_argument("--endpoint", help="Remote Smart Data Agent base URL.")
        command.add_argument("--token-env", default="SMART_DATA_AGENT_REPORT_TOKEN", help="Environment variable containing the channel binding token.")
        command.add_argument("--token-keychain-service", default="smart-data-agent-report-token", help="macOS Keychain service used when --token-env is absent.")
        command.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help=f"Optional non-secret config file (default: {DEFAULT_CONFIG}).")
        command.add_argument("--timeout", type=float, default=20, help="HTTP timeout in seconds.")
        command.add_argument("--json", action="store_true", help="Print the server response as JSON.")

    systems = subcommands.add_parser("systems", help="Discover backend systems configured in Bridge; clients do not reinstall when this list changes.")
    common(systems)

    context = subcommands.add_parser("context", help="Read one exact system's authorized context.")
    common(context)
    context.add_argument("--system", default="", help="Exact system ID from `systems`; omitted only for legacy SDA compatibility.")

    data = subcommands.add_parser("data", help="Legacy SDA alias for a bounded authorized raw-table read.")
    common(data)
    data.add_argument("--source-key", required=True, help="SDA sourceKey returned by the channel context command.")
    data.add_argument("--columns", default="", help="Optional comma-separated CSV column names.")
    data.add_argument("--limit", type=int, default=100, help="Rows to read (maximum 500).")

    read = subcommands.add_parser("read", help="Read one allowlisted resource from an exact registered system.")
    common(read)
    read.add_argument("--system", required=True, help="Exact system ID from `systems`.")
    read.add_argument("--resource", required=True, help="Allowlisted resource name from the system manifest.")
    source = read.add_mutually_exclusive_group()
    source.add_argument("--input", type=Path, help="Optional JSON input for the system read.")
    source.add_argument("--stdin", action="store_true", help="Read optional JSON input from stdin.")

    action = subcommands.add_parser("action", help="Run one allowlisted idempotent backend configuration action.")
    common(action)
    action.add_argument("--system", required=True, help="Exact system ID from `systems`.")
    action.add_argument("--action", required=True, help="Exact action name from the system manifest.")
    action.add_argument("--operation-id", required=True, help="Stable idempotency ID for this requested configuration change.")
    source = action.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="JSON action input.")
    source.add_argument("--stdin", action="store_true", help="Read JSON action input from stdin.")

    sync = subcommands.add_parser("sync", help="Synchronize analysis output to an exact registered system.")
    common(sync)
    sync.add_argument("--system", required=True, help="Exact system ID from `systems`.")
    sync.add_argument("--operation-id", required=True, help="Stable analysis run ID used for idempotent synchronization.")
    source = sync.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="JSON analysis package.")
    source.add_argument("--stdin", action="store_true", help="Read JSON analysis package from stdin.")

    evidence = subcommands.add_parser("evidence", help=f"Return {client_label} operation logic as review-only learning material.")
    common(evidence)
    evidence.add_argument("--system", default="", help="Exact system ID; omitted only for legacy SDA compatibility.")
    evidence.add_argument("--operation-id", default="", help="Stable operation ID; required with --system.")
    evidence.add_argument("--source-key", action="append", default=[], help="Legacy SDA sourceKey; repeat for multiple tables.")
    source = evidence.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="Path to the evidence JSON file.")
    source.add_argument("--stdin", action="store_true", help="Read evidence JSON from stdin.")


def _publish(args: argparse.Namespace) -> int:
    try:
        payload = _read_payload(args.input, args.stdin)
        _validate_channel_payload(payload, args.channel)
        endpoint = _endpoint(args.endpoint, args.config)
        if args.dry_run:
            print(json.dumps(_safe_summary(payload, args.channel, endpoint), ensure_ascii=False))
            return 0
        token = _token(args.token_env, args.token_keychain_service)
        if not token:
            raise ValueError("token_missing: set the token environment variable or configure the platform secret store")
        response_payload = _post(endpoint, token, payload, args.timeout)
        if args.json:
            print(json.dumps(response_payload, ensure_ascii=False))
        else:
            result = response_payload.get("result") if isinstance(response_payload.get("result"), dict) else {}
            print(f"已同步报告：{result.get('title') or '未命名'} (channel={response_payload.get('channel') or args.channel}, report_id={result.get('id') or 'unknown'})")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"SDA: {exc}", file=sys.stderr)
        return 2
    except error.HTTPError as exc:
        print(f"SDA: remote_rejected:http_{exc.code}{_http_error_message(exc)}", file=sys.stderr)
        return 3
    except error.URLError as exc:
        print(f"SDA: remote_unreachable:{exc.reason}", file=sys.stderr)
        return 4


def _connect(args: argparse.Namespace) -> int:
    try:
        base_endpoint = _base_endpoint(args.endpoint, args.config)
        service = str(args.token_keychain_service or _default_token_service(args.channel)).strip()
        verifier = secrets.token_urlsafe(32)
        verifier_hash = hashlib.sha256(verifier.encode("utf-8")).hexdigest()
        device_name = str(args.device_name or f"{socket.gethostname()} · {platform.system()}").strip()[:160]
        started = _request_json(
            base_endpoint + "/api/integrations/bridge/enrollment/start",
            "",
            {"channel": args.channel, "device_name": device_name, "verifier_hash": verifier_hash},
            min(max(1, args.timeout), 20),
            channel=args.channel,
        )
        verification_path = str(started.get("verification_uri_complete") or "").strip()
        if not verification_path:
            raise ValueError("bridge_enrollment_verification_url_missing")
        app_endpoint = _app_endpoint(args.app_url, args.config, base_endpoint)
        verification_url = parse.urljoin(app_endpoint + "/", verification_path.lstrip("/"))
        print(f"请在浏览器点击“允许连接”：{verification_url}", file=sys.stderr)
        if not args.no_open:
            webbrowser.open(verification_url, new=1, autoraise=True)
        deadline = time.monotonic() + max(30, min(float(args.timeout), 900))
        interval = max(1, min(int(started.get("interval") or 2), 10))
        result: dict[str, Any] = {}
        while time.monotonic() < deadline:
            result = _request_json(
                base_endpoint + "/api/integrations/bridge/enrollment/poll",
                "",
                {"device_code": started.get("device_code"), "verifier": verifier},
                min(max(1, args.timeout), 20),
                channel=args.channel,
            )
            if result.get("status") == "authorized":
                break
            if result.get("status") != "authorization_pending":
                raise ValueError(str(result.get("status") or "bridge_enrollment_state_invalid"))
            time.sleep(interval)
        if result.get("status") != "authorized":
            raise ValueError("bridge_enrollment_approval_timeout")
        token = str(result.pop("token", "") or "")
        if not token:
            raise ValueError("bridge_enrollment_token_missing")
        _store_platform_token(token, service)
        context = _request_json(
            base_endpoint + "/api/integrations/bridge/manifest",
            token,
            None,
            min(max(1, args.timeout), 20),
            method="GET",
            channel=args.channel,
        )
        _validate_bridge_manifest(context, args.channel)
        safe_result = {
            "connected": True,
            "channel": args.channel,
            "binding": result.get("binding"),
            "system_count": len(context.get("systems") or []),
        }
        if args.json:
            print(json.dumps(safe_result, ensure_ascii=False))
        else:
            print(f"Universal Bridge 已连接：channel={args.channel}，可发现系统={safe_result['system_count']} 个。")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"SDA: {exc}", file=sys.stderr)
        return 2
    except error.HTTPError as exc:
        print(f"SDA: remote_rejected:http_{exc.code}{_http_error_message(exc)}", file=sys.stderr)
        return 3
    except error.URLError as exc:
        print(f"SDA: remote_unreachable:{exc.reason}", file=sys.stderr)
        return 4


def _read_payload(path: Path | None, read_stdin: bool) -> dict[str, Any]:
    raw = sys.stdin.read() if read_stdin else path.read_text(encoding="utf-8") if path else ""
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("report_payload_must_be_a_json_object")
    return payload


def _validate_channel_payload(payload: dict[str, Any], channel: str) -> None:
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    if str(source.get("channel") or "").strip() not in {"", channel}:
        raise ValueError("channel_does_not_match_payload_source")
    if not str(source.get("run_id") or source.get("runId") or "").strip():
        raise ValueError("source.run_id_is_required")
    report = payload.get("report") if isinstance(payload.get("report"), dict) else payload
    if not str(report.get("title") or "").strip():
        raise ValueError("report.title_is_required")


def _endpoint(value: str | None, config_path: Path) -> str:
    return _api_endpoint(value, config_path, "/api/integrations/reports")


def _api_endpoint(value: str | None, config_path: Path, path: str) -> str:
    endpoint = _base_endpoint(value, config_path)
    return endpoint if endpoint.endswith(path) else endpoint + path


def _base_endpoint(value: str | None, config_path: Path) -> str:
    endpoint = str(value or _load_config(config_path).get("endpoint") or "").strip().rstrip("/")
    if not endpoint:
        raise ValueError("endpoint_required: set --endpoint or report-cli.json endpoint")
    for suffix in (
        "/api/integrations/reports",
        "/api/integrations/workbuddy/context",
        "/api/integrations/codex/context",
        "/api/integrations/qwork/context",
    ):
        if endpoint.endswith(suffix):
            endpoint = endpoint[: -len(suffix)]
            break
    parsed = parse.urlsplit(endpoint)
    if not parsed.hostname or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("endpoint_invalid: use an SDA HTTPS root URL without credentials, query or fragment")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("endpoint_https_required")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("endpoint_invalid_scheme")
    if parsed.path not in {"", "/"}:
        raise ValueError("endpoint_root_path_required")
    return endpoint.rstrip("/")


def _app_endpoint(value: str | None, config_path: Path, api_endpoint: str) -> str:
    configured = str(value or _load_config(config_path).get("app_url") or "").strip().rstrip("/")
    if configured:
        return configured
    parsed = parse.urlsplit(api_endpoint)
    if parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == 8788:
        host = f"[{parsed.hostname}]" if ":" in str(parsed.hostname or "") else parsed.hostname
        return parse.urlunsplit((parsed.scheme, f"{host}:5174", "", "", "")).rstrip("/")
    return api_endpoint


def _bridge(args: argparse.Namespace, channel: str, command: str) -> int:
    try:
        generic_path = {
            "systems": "/api/integrations/bridge/manifest",
            "context": "/api/integrations/bridge/context",
            "read": "/api/integrations/bridge/read",
            "action": "/api/integrations/bridge/action",
            "sync": "/api/integrations/bridge/sync",
            "evidence": "/api/integrations/bridge/evidence",
        }
        if command == "data":
            path = f"/api/integrations/{channel}/data"
        elif command == "context" and not args.system:
            path = f"/api/integrations/{channel}/context"
        elif command == "evidence" and not args.system:
            path = f"/api/integrations/{channel}/evidence"
        else:
            path = generic_path[command]
        endpoint = _api_endpoint(args.endpoint, args.config, path)
        token = _token(args.token_env, args.token_keychain_service)
        if not token:
            raise ValueError("token_missing: set the token environment variable or configure the platform secret store")
        if command == "systems":
            response_payload = _request_json(endpoint, token, None, args.timeout, method="GET", channel=channel)
            _validate_bridge_manifest(response_payload, channel)
        elif command == "context" and args.system:
            response_payload = _request_json(endpoint, token, {"system_id": args.system}, args.timeout, channel=channel)
        elif command == "context":
            response_payload = _request_json(endpoint, token, None, args.timeout, method="GET", channel=channel)
        elif command == "data":
            columns = [item.strip() for item in str(args.columns or "").split(",") if item.strip()]
            response_payload = _request_json(endpoint, token, {"source_key": args.source_key, "columns": columns, "limit": args.limit}, args.timeout, channel=channel)
        elif command == "read":
            read_input = _read_optional_payload(args.input, args.stdin)
            response_payload = _request_json(endpoint, token, {"system_id": args.system, "resource": args.resource, "input": read_input}, args.timeout, channel=channel)
        elif command == "action":
            action_input = _read_payload(args.input, args.stdin)
            response_payload = _request_json(endpoint, token, {"system_id": args.system, "action": args.action, "operation_id": args.operation_id, "input": action_input}, args.timeout, channel=channel)
        elif command == "sync":
            sync_input = _read_payload(args.input, args.stdin)
            response_payload = _request_json(endpoint, token, {"system_id": args.system, "operation_id": args.operation_id, "input": sync_input}, args.timeout, channel=channel)
        elif args.system:
            if not args.operation_id:
                raise ValueError("operation_id_is_required_with_system")
            evidence = _read_payload(args.input, args.stdin)
            response_payload = _request_json(endpoint, token, {"system_id": args.system, "operation_id": args.operation_id, "input": evidence}, args.timeout, channel=channel)
        else:
            evidence = _read_payload(args.input, args.stdin)
            _bind_evidence_sources(evidence, args.source_key)
            response_payload = _request_json(endpoint, token, evidence, args.timeout, channel=channel)
        if args.json or command != "evidence":
            print(json.dumps(response_payload, ensure_ascii=False))
        else:
            print(f"已回传 {channel} 分析材料；记忆与 Skill 候选仍需 SDA 复核后才会启用。")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"SDA: {exc}", file=sys.stderr)
        return 2
    except error.HTTPError as exc:
        print(f"SDA: remote_rejected:http_{exc.code}{_http_error_message(exc)}", file=sys.stderr)
        return 3
    except error.URLError as exc:
        print(f"SDA: remote_unreachable:{exc.reason}", file=sys.stderr)
        return 4


def _read_optional_payload(path: Path | None, read_stdin: bool) -> dict[str, Any]:
    if path is None and not read_stdin:
        return {}
    return _read_payload(path, read_stdin)


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    parsed = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(parsed, dict):
        raise ValueError("config_must_be_a_json_object")
    return parsed


def _post(endpoint: str, token: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    return _request_json(endpoint, token, payload, timeout, channel=str(source.get("channel") or "external"))


def _request_json(endpoint: str, token: str, payload: dict[str, Any] | None, timeout: float, *, method: str = "POST", channel: str = "external") -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json", "User-Agent": f"smart-data-agent-bridge/{channel}/4"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if channel in {"workbuddy", "codex", "qwork"}:
        headers["X-Bridge-Channel"] = channel
    req = request.Request(endpoint, data=body, method=method, headers=headers)
    with request.urlopen(req, timeout=max(1, timeout)) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("remote_response_must_be_a_json_object")
    return parsed


def _bind_evidence_sources(evidence: dict[str, Any], source_keys: list[str]) -> None:
    normalized = [str(value or "").strip() for value in source_keys if str(value or "").strip()]
    references = evidence.get("references")
    if isinstance(references, list):
        declared = [str(item.get("source_key") or item.get("sourceKey") or "").strip() for item in references if isinstance(item, dict)]
        if normalized and normalized != declared:
            raise ValueError("source_keys_do_not_match_evidence_references")
        return
    if len(normalized) != 1:
        raise ValueError("evidence.references_is_required_for_multiple_sources")
    evidence["source_key"] = normalized[0]


def _validate_bridge_manifest(payload: dict[str, Any], channel: str) -> None:
    if payload.get("schema_version") != "bridge_manifest_v1":
        raise ValueError("bridge_manifest_schema_unsupported")
    if str(payload.get("contract_version") or "") != "1.0":
        raise ValueError("bridge_contract_version_unsupported")
    declared_channel = str(payload.get("channel") or channel).strip().lower()
    if declared_channel != channel:
        raise ValueError("bridge_manifest_channel_mismatch")
    if set(payload.get("modules") or []) != {"analysis_sync", "configuration", "read", "learning"}:
        raise ValueError("bridge_manifest_modules_incomplete")
    systems = payload.get("systems")
    if not isinstance(systems, list):
        raise ValueError("bridge_manifest_systems_invalid")
    system_ids = [str(item.get("id") or "").strip() for item in systems if isinstance(item, dict)]
    if not system_ids or any(not system_id for system_id in system_ids) or len(system_ids) != len(set(system_ids)):
        raise ValueError("bridge_manifest_systems_invalid")


def _token(environment_name: str, keychain_service: str) -> str:
    value = os.getenv(environment_name, "").strip()
    if value:
        return value
    if sys.platform == "darwin" and keychain_service.strip():
        completed = subprocess.run(["security", "find-generic-password", "-a", os.getenv("USER", ""), "-s", keychain_service.strip(), "-w"], text=True, capture_output=True, check=False)
        return completed.stdout.strip() if completed.returncode == 0 else ""
    if sys.platform == "win32":
        return _windows_dpapi_token(keychain_service)
    return ""


def _windows_dpapi_token(keychain_service: str = "smart-data-agent-report-token") -> str:
    token_path = _windows_token_path(keychain_service)
    if not token_path.exists():
        return ""
    command = """
$raw = Get-Content -Raw -LiteralPath $env:SMART_DATA_AGENT_REPORT_TOKEN_FILE
if ([string]::IsNullOrWhiteSpace($raw)) { exit 0 }
$secure = ConvertTo-SecureString $raw
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
"""
    environment = os.environ.copy()
    environment["SMART_DATA_AGENT_REPORT_TOKEN_FILE"] = str(token_path)
    completed = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], text=True, capture_output=True, check=False, env=environment)
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _default_token_service(channel: str) -> str:
    return "smart-data-agent-report-token" if channel == "workbuddy" else f"smart-data-agent-bridge-{channel}"


def _store_platform_token(token: str, keychain_service: str) -> None:
    if not token:
        raise ValueError("bridge_enrollment_token_missing")
    if sys.platform == "darwin":
        completed = subprocess.run(
            ["security", "add-generic-password", "-U", "-a", os.getenv("USER", ""), "-s", keychain_service, "-w"],
            input=f"{token}\n{token}\n",
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise OSError("bridge_keychain_write_failed")
        return
    if sys.platform == "win32":
        command = """
$plain = [Console]::In.ReadToEnd()
if ([string]::IsNullOrWhiteSpace($plain)) { exit 2 }
$secure = ConvertTo-SecureString $plain -AsPlainText -Force
$secure | ConvertFrom-SecureString
"""
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            input=token,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            raise OSError("bridge_dpapi_write_failed")
        token_path = _windows_token_path(keychain_service)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(completed.stdout.strip(), encoding="utf-8")
        return
    raise OSError("bridge_platform_secret_store_unsupported")


def _safe_summary(payload: dict[str, Any], channel: str, endpoint: str) -> dict[str, Any]:
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    report = payload.get("report") if isinstance(payload.get("report"), dict) else payload
    rows = report.get("rows") if isinstance(report.get("rows"), list) else report.get("data")
    return {"valid": True, "channel": channel, "endpoint": endpoint, "source_run_id": str(source.get("run_id") or source.get("runId") or ""), "title": str(report.get("title") or ""), "row_count": len(rows) if isinstance(rows, list) else 0}


def _http_error_message(exc: error.HTTPError) -> str:
    try:
        parsed = json.loads(exc.read(4096).decode("utf-8", errors="replace"))
        if isinstance(parsed, dict):
            return ":" + str(parsed.get("error") or parsed.get("message") or "")[:300]
    except Exception:
        pass
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
