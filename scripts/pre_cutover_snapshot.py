#!/usr/bin/env python3
"""Capture and verify a secret-free rollback point before production cutover."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.request
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.deployment_identity import IDENTITY_KEYS, normalized_capabilities, normalized_image_platform


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "release" / "pre-cutover-snapshot.json"
CANDIDATE = ROOT / "artifacts" / "release" / "candidate-identity.json"


def _sha(value: str, code: str) -> str:
    normalized = str(value or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", normalized):
        raise SystemExit(code)
    return normalized


def _docker_json(*command: str) -> dict[str, Any]:
    completed = subprocess.run(("docker", *command), cwd=ROOT, capture_output=True, text=True)
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or "pre_cutover_docker_inspect_failed")
    payload = json.loads(completed.stdout)
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise SystemExit("pre_cutover_docker_inspect_invalid")
    return payload[0]


def build_snapshot(
    *,
    base_url: str,
    target_release_sha: str,
    candidate: dict[str, Any],
    health: dict[str, Any],
    container: dict[str, Any],
    image: dict[str, Any],
) -> dict[str, Any]:
    target_sha = _sha(target_release_sha, "pre_cutover_target_sha_invalid")
    candidate_identity = candidate.get("identity") if isinstance(candidate.get("identity"), dict) else {}
    if candidate_identity.get("commit_sha") != target_sha:
        raise SystemExit("pre_cutover_candidate_identity_mismatch")
    candidate_container = candidate.get("container") if isinstance(candidate.get("container"), dict) else {}
    candidate_platform = candidate_container.get("platform")
    if not isinstance(candidate_platform, dict):
        raise SystemExit("pre_cutover_candidate_platform_missing")
    if health.get("ready") is not True:
        raise SystemExit("pre_cutover_current_production_not_ready")
    container_id = str(container.get("Id") or "").strip()
    rollback_image_id = str(container.get("Image") or image.get("Id") or "").strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", rollback_image_id):
        raise SystemExit("pre_cutover_rollback_image_id_invalid")
    if str(image.get("Id") or "") != rollback_image_id:
        raise SystemExit("pre_cutover_container_image_mismatch")
    rollback_platform = normalized_image_platform(image)
    if candidate_platform != rollback_platform:
        raise SystemExit("pre_cutover_candidate_production_platform_mismatch")
    state = container.get("State") if isinstance(container.get("State"), dict) else {}
    if state.get("Running") is not True:
        raise SystemExit("pre_cutover_current_container_not_running")
    labels = (image.get("Config") or {}).get("Labels") if isinstance(image.get("Config"), dict) else {}
    labels = labels if isinstance(labels, dict) else {}
    rollback_revision = _sha(str(labels.get("org.opencontainers.image.revision") or ""), "pre_cutover_rollback_revision_invalid")
    build = health.get("build") if isinstance(health.get("build"), dict) else {}
    runtime_revision = str(build.get("commit_sha") or "").strip().lower()
    if runtime_revision and runtime_revision != rollback_revision:
        raise SystemExit("pre_cutover_runtime_image_revision_mismatch")
    repo_digests = sorted(str(item) for item in image.get("RepoDigests") or [] if re.fullmatch(r".+@sha256:[0-9a-f]{64}", str(item)))
    runtime = health.get("runtime") if isinstance(health.get("runtime"), dict) else {}
    return {
        "schema_version": "smart-data-agent-pre-cutover/v2",
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "target_release": {
            "commit_sha": target_sha,
            "candidate_image_reference": str(candidate_identity.get("image_reference") or ""),
            "platform": candidate_platform,
        },
        "current_production": {
            "base_url": base_url.rstrip("/"),
            "container_id": container_id,
            "container_name": str(container.get("Name") or "").removeprefix("/"),
            "runtime_instance_id": str(runtime.get("instance_id") or ""),
            "build_identity": {key: str(build.get(key) or "") for key in IDENTITY_KEYS},
            "capability_contract": normalized_capabilities(health.get("capabilities")),
        },
        "rollback": {
            "image_id": rollback_image_id,
            "repo_digests": repo_digests,
            "revision": rollback_revision,
            "source": str(labels.get("org.opencontainers.image.source") or ""),
            "created": str(labels.get("org.opencontainers.image.created") or ""),
            "platform": rollback_platform,
        },
    }


def capture(base_url: str, container_ref: str, target_release_sha: str) -> dict[str, Any]:
    if not CANDIDATE.is_file():
        raise SystemExit("pre_cutover_candidate_receipt_missing")
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/ready", timeout=15) as response:
        health = json.load(response)
    container = _docker_json("container", "inspect", container_ref)
    image_id = str(container.get("Image") or "")
    image = _docker_json("image", "inspect", image_id)
    payload = build_snapshot(
        base_url=base_url,
        target_release_sha=target_release_sha,
        candidate=candidate,
        health=health,
        container=container,
        image=image,
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(OUTPUT)
    return payload


def verify(path: Path, target_release_sha: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "smart-data-agent-pre-cutover/v2":
        raise SystemExit("pre_cutover_snapshot_schema_invalid")
    target_sha = _sha(target_release_sha, "pre_cutover_target_sha_invalid")
    if (payload.get("target_release") or {}).get("commit_sha") != target_sha:
        raise SystemExit("pre_cutover_snapshot_target_mismatch")
    rollback = payload.get("rollback") if isinstance(payload.get("rollback"), dict) else {}
    image_id = str(rollback.get("image_id") or "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise SystemExit("pre_cutover_rollback_image_id_invalid")
    image = _docker_json("image", "inspect", image_id)
    if str(image.get("Id") or "") != image_id:
        raise SystemExit("pre_cutover_rollback_image_unavailable")
    if normalized_image_platform(image) != rollback.get("platform"):
        raise SystemExit("pre_cutover_rollback_image_platform_changed")
    labels = (image.get("Config") or {}).get("Labels") if isinstance(image.get("Config"), dict) else {}
    labels = labels if isinstance(labels, dict) else {}
    if str(labels.get("org.opencontainers.image.revision") or "") != str(rollback.get("revision") or ""):
        raise SystemExit("pre_cutover_rollback_image_revision_changed")
    return {
        "status": "passed",
        "target_release_sha": target_sha,
        "rollback_image_id": image_id,
        "rollback_revision": rollback.get("revision"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("base_url")
    capture_parser.add_argument("container_ref")
    capture_parser.add_argument("target_release_sha")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("snapshot")
    verify_parser.add_argument("target_release_sha")
    args = parser.parse_args()
    if args.command == "capture":
        result = capture(args.base_url, args.container_ref, args.target_release_sha)
    else:
        result = verify(Path(args.snapshot), args.target_release_sha)
    print(json.dumps({"status": "passed", **result}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
