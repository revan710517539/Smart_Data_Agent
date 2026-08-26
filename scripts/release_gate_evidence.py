#!/usr/bin/env python3
"""Incrementally record the single release gate without leaking secrets."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "artifacts" / "release" / "release-gate-report.json"
IDENTITY = ROOT / "artifacts" / "release" / "release-identity.json"
PYTHON_MARKER = ROOT / "artifacts" / "release" / "python-environment.json"
TOOLCHAIN_LOCK = ROOT / "configs" / "release" / "toolchain-lock.json"
SUPPORTED_TARGET_PLATFORMS = {"linux/amd64", "linux/arm64"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write(payload: dict) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    temporary = REPORT.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(REPORT)


def _read() -> dict:
    if not REPORT.is_file():
        raise SystemExit("release_gate_evidence_not_started")
    return json.loads(REPORT.read_text(encoding="utf-8"))


def _version(*command: str) -> str:
    try:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    except OSError:
        return "unavailable"
    if completed.returncode != 0:
        return "unavailable"
    return (completed.stdout or completed.stderr).strip().splitlines()[0]


def _sha(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", normalized):
        raise SystemExit("release_gate_evidence_commit_sha_invalid")
    return normalized


def _json_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _toolchain_image_id(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", normalized):
        raise SystemExit("release_gate_receipt_toolchain_image_id_invalid")
    return normalized


def _target_platform(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_TARGET_PLATFORMS:
        raise SystemExit("release_gate_receipt_target_platform_invalid")
    return normalized


def verify_receipt(commit_sha: str, scope: str, toolchain_image_id: str, target_platform: str) -> dict:
    """Fail closed unless this exact source and toolchain produced the passed gate."""

    payload = _read()
    expected_sha = _sha(commit_sha)
    expected_toolchain = _toolchain_image_id(toolchain_image_id)
    expected_platform = _target_platform(target_platform)
    if payload.get("schema_version") != "smart-data-agent-release-gate/v3":
        raise SystemExit("release_gate_receipt_schema_invalid")
    if payload.get("status") != "passed":
        raise SystemExit("release_gate_receipt_not_passed")
    if payload.get("scope") != scope:
        raise SystemExit("release_gate_receipt_scope_mismatch")
    if payload.get("commit_sha") != expected_sha:
        raise SystemExit("release_gate_receipt_commit_sha_mismatch")
    environment = payload.get("environment")
    if not isinstance(environment, dict):
        raise SystemExit("release_gate_receipt_environment_invalid")
    if environment.get("toolchain_image_id") != expected_toolchain:
        raise SystemExit("release_gate_receipt_toolchain_image_mismatch")
    if environment.get("target_platform") != expected_platform:
        raise SystemExit("release_gate_receipt_target_platform_mismatch")
    identity = payload.get("identity")
    if not isinstance(identity, dict) or identity.get("commit_sha") != expected_sha:
        raise SystemExit("release_gate_receipt_identity_mismatch")
    result = payload.get("result")
    if not isinstance(result, dict) or result.get("failed_steps") != []:
        raise SystemExit("release_gate_receipt_result_invalid")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--commit-sha", required=True)
    start.add_argument("--scope", choices=("build", "candidate"), required=True)
    step = subparsers.add_parser("step")
    step.add_argument("--name", required=True)
    step.add_argument("--started-at", required=True)
    step.add_argument("--completed-at", required=True)
    step.add_argument("--status", choices=("passed", "failed"), required=True)
    step.add_argument("--exit-code", required=True, type=int)
    step.add_argument("argv", nargs=argparse.REMAINDER)
    finish = subparsers.add_parser("finish")
    finish.add_argument("--status", choices=("passed", "failed"), required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--commit-sha", required=True)
    verify.add_argument("--scope", choices=("build", "candidate"), required=True)
    verify.add_argument("--toolchain-image-id", required=True)
    verify.add_argument("--target-platform", required=True)
    args = parser.parse_args()

    if args.command == "verify":
        payload = verify_receipt(args.commit_sha, args.scope, args.toolchain_image_id, args.target_platform)
        print(json.dumps({
            "status": "passed",
            "commit_sha": payload["commit_sha"],
            "scope": payload["scope"],
            "toolchain_image_id": payload["environment"]["toolchain_image_id"],
            "target_platform": payload["environment"]["target_platform"],
        }, ensure_ascii=False, sort_keys=True))
        return

    if args.command == "start":
        offline = os.getenv("SMART_DATA_AGENT_RELEASE_OFFLINE", "false")
        if offline not in {"true", "false"}:
            raise SystemExit("SMART_DATA_AGENT_RELEASE_OFFLINE must be exactly true or false")
        target_platform = _target_platform(os.getenv("SMART_DATA_AGENT_TARGET_PLATFORM", ""))
        _write({
            "schema_version": "smart-data-agent-release-gate/v3",
            "commit_sha": _sha(args.commit_sha),
            "scope": args.scope,
            "status": "in_progress",
            "started_at": _now(),
            "completed_at": None,
            "environment": {
                "platform": {
                    "system": platform.system(),
                    "release": platform.release(),
                    "machine": platform.machine(),
                },
                "node": _version("node", "--version"),
                "npm": _version("npm", "--version"),
                "python": platform.python_version(),
                "uv": _version("uv", "--version"),
                "toolchain_image_id": os.getenv("SMART_DATA_AGENT_RELEASE_TOOLCHAIN_IMAGE_ID", ""),
                "target_platform": target_platform,
                "offline": offline == "true",
                "cache_manifest_sha256": os.getenv("SMART_DATA_AGENT_RELEASE_CACHE_MANIFEST_SHA256", ""),
                "toolchain_contract": _json_file(TOOLCHAIN_LOCK),
            },
            "steps": [],
        })
        return

    payload = _read()
    if args.command == "step":
        argv = list(args.argv)
        if argv[:1] == ["--"]:
            argv = argv[1:]
        payload.setdefault("steps", []).append({
            "name": args.name,
            "command": argv,
            "started_at": args.started_at,
            "completed_at": args.completed_at,
            "status": args.status,
            "exit_code": args.exit_code,
        })
        if args.status == "failed":
            payload["status"] = "failed"
        _write(payload)
        return

    payload["status"] = args.status
    payload["completed_at"] = _now()
    payload["identity"] = _json_file(IDENTITY)
    payload["python_environment"] = _json_file(PYTHON_MARKER)
    payload["result"] = {
        "total_steps": len(payload.get("steps") or []),
        "failed_steps": [
            item.get("name")
            for item in payload.get("steps") or []
            if item.get("status") != "passed"
        ],
    }
    if args.status == "failed" and not payload["result"]["failed_steps"]:
        payload["result"]["failed_steps"] = ["unrecorded_gate_failure"]
    if args.status == "passed" and payload["result"]["failed_steps"]:
        raise SystemExit("release_gate_evidence_cannot_pass_with_failed_steps")
    _write(payload)


if __name__ == "__main__":
    main()
