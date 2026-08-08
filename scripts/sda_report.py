#!/usr/bin/env python3
"""Publish a structured external analysis result to Smart Data Agent.

This client deliberately reads its credential only from an environment
variable.  It can therefore be installed on a workstation while the Smart
Data Agent API lives on another host.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib import error, request


DEFAULT_CONFIG = Path.home() / ".config" / "smart-data-agent" / "report-cli.json"


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
    args = parser.parse_args(argv)
    if args.command == "publish":
        return _publish(args)
    return 2


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
            raise ValueError(f"token_missing: set {args.token_env} or macOS Keychain service {args.token_keychain_service}")
        response_payload = _post(endpoint, token, payload, args.timeout)
        if args.json:
            print(json.dumps(response_payload, ensure_ascii=False))
        else:
            result = response_payload.get("result") if isinstance(response_payload.get("result"), dict) else {}
            print(
                "已同步报告："
                f"{result.get('title') or '未命名'} "
                f"(channel={response_payload.get('channel') or args.channel}, report_id={result.get('id') or 'unknown'})"
            )
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"SDA: {exc}", file=sys.stderr)
        return 2
    except error.HTTPError as exc:
        detail = _http_error_message(exc)
        print(f"SDA: remote_rejected:http_{exc.code}{detail}", file=sys.stderr)
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
    supplied_channel = str(source.get("channel") or "").strip()
    if supplied_channel and supplied_channel != channel:
        raise ValueError("channel_does_not_match_payload_source")
    run_id = str(source.get("run_id") or source.get("runId") or "").strip()
    if not run_id:
        raise ValueError("source.run_id_is_required")
    report = payload.get("report") if isinstance(payload.get("report"), dict) else payload
    if not str(report.get("title") or "").strip():
        raise ValueError("report.title_is_required")


def _endpoint(value: str | None, config_path: Path) -> str:
    config = _load_config(config_path)
    endpoint = str(value or config.get("endpoint") or "").strip().rstrip("/")
    if not endpoint:
        raise ValueError("endpoint_required: set --endpoint or report-cli.json endpoint")
    return endpoint if endpoint.endswith("/api/integrations/reports") else endpoint + "/api/integrations/reports"


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("config_must_be_a_json_object")
    return parsed


def _post(endpoint: str, token: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "smart-data-agent-report-cli/1",
        },
    )
    with request.urlopen(req, timeout=max(1, timeout)) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("remote_response_must_be_a_json_object")
    return parsed


def _token(environment_name: str, keychain_service: str) -> str:
    value = os.getenv(environment_name, "").strip()
    if value or sys.platform != "darwin" or not keychain_service.strip():
        return value
    completed = subprocess.run(
        ["security", "find-generic-password", "-a", os.getenv("USER", ""), "-s", keychain_service.strip(), "-w"],
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _safe_summary(payload: dict[str, Any], channel: str, endpoint: str) -> dict[str, Any]:
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    report = payload.get("report") if isinstance(payload.get("report"), dict) else payload
    rows = report.get("rows") if isinstance(report.get("rows"), list) else report.get("data")
    return {
        "valid": True,
        "channel": channel,
        "endpoint": endpoint,
        "source_run_id": str(source.get("run_id") or source.get("runId") or ""),
        "title": str(report.get("title") or ""),
        "row_count": len(rows) if isinstance(rows, list) else 0,
    }


def _http_error_message(exc: error.HTTPError) -> str:
    try:
        body = exc.read(4096).decode("utf-8", errors="replace")
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            return ":" + str(parsed.get("error") or parsed.get("message") or "")[:300]
    except Exception:
        pass
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
