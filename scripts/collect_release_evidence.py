#!/usr/bin/env python3
"""Create a secret-free evidence pack for an immutable Smart Data Agent image."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import shutil
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_TARGET_PLATFORMS = {"linux/amd64", "linux/arm64"}


def _run(*args: str) -> str:
    completed = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or f"release_evidence_command_failed:{' '.join(args)}")
    return completed.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("commit_sha")
    args = parser.parse_args()
    sha = args.commit_sha.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise SystemExit("release_evidence_commit_sha_invalid")
    inspect_payload = json.loads(_run("docker", "image", "inspect", args.image))
    if not isinstance(inspect_payload, list) or len(inspect_payload) != 1:
        raise SystemExit("release_evidence_image_inspect_invalid")
    image: dict[str, Any] = inspect_payload[0]
    image_platform = f"{str(image.get('Os') or '').lower()}/{str(image.get('Architecture') or '').lower()}"
    target_platform = os.getenv("SMART_DATA_AGENT_TARGET_PLATFORM", "").strip().lower()
    if target_platform not in SUPPORTED_TARGET_PLATFORMS:
        raise SystemExit("release_evidence_target_platform_invalid")
    if image_platform != target_platform:
        raise SystemExit("release_evidence_image_platform_mismatch")
    labels = ((image.get("Config") or {}).get("Labels") or {})
    if labels.get("org.opencontainers.image.revision") != sha:
        raise SystemExit("release_evidence_image_revision_mismatch")
    source_url = str(labels.get("org.opencontainers.image.source") or "")
    if not source_url.startswith("https://"):
        raise SystemExit("release_evidence_image_source_invalid")
    identity_path = ROOT / "artifacts" / "release" / "release-identity.json"
    gate_report_path = ROOT / "artifacts" / "release" / "release-gate-report.json"
    python_marker_path = ROOT / "artifacts" / "release" / "python-environment.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8")) if identity_path.is_file() else {}
    if identity.get("commit_sha") != sha:
        raise SystemExit("release_evidence_identity_mismatch")
    label_contract = {
        "com.smartdataagent.source-archive-sha256": "source_archive_sha256",
        "com.smartdataagent.dependency-lock-sha256": "dependency_lock_sha256",
        "com.smartdataagent.frontend-assets-sha256": "frontend_assets_sha256",
        "com.smartdataagent.release-toolchain-sha256": "release_toolchain_sha256",
    }
    for label, identity_key in label_contract.items():
        if labels.get(label) != identity.get(identity_key):
            raise SystemExit(f"release_evidence_image_label_mismatch:{label}")
    if not gate_report_path.is_file():
        raise SystemExit("release_evidence_gate_report_missing")
    if not python_marker_path.is_file():
        raise SystemExit("release_evidence_python_marker_missing")
    sbom = ROOT / "artifacts" / "sbom" / "smart-data-agent.cdx.json"
    if not sbom.is_file():
        raise SystemExit("release_evidence_sbom_missing")
    evidence_dir = ROOT / "artifacts" / "releases" / sha
    evidence_dir.mkdir(parents=True, exist_ok=True)
    critical = [
        ROOT / "Dockerfile",
        ROOT / "Dockerfile.release-toolchain",
        ROOT / "docker-compose.server.yml",
        ROOT / "DEVELOPMENT.md",
        ROOT / ".env.server-development.example",
        ROOT / "configs" / "deployment" / "smart-data-agent-docker-mss.service",
        ROOT / "configs" / "release" / "toolchain-lock.json",
        ROOT / "configs" / "deployment" / "mysql-migration-checksums.json",
        ROOT / "scripts" / "data-crawler-mount-contract.sh",
        ROOT / "scripts" / "data_crawler_mount_contract.py",
        ROOT / "scripts" / "deployment_identity.py",
        ROOT / "scripts" / "mysql_backup_receipt.py",
        ROOT / "scripts" / "mysql_migration_receipt.py",
        ROOT / "scripts" / "server-development-container.sh",
        ROOT / "uv.lock",
        ROOT / "package-lock.json",
        identity_path,
        gate_report_path,
        python_marker_path,
        sbom,
    ]
    deployment_receipts = [
        ROOT / "artifacts" / "release" / name
        for name in ("candidate-identity.json", "production-identity.json")
        if (ROOT / "artifacts" / "release" / name).is_file()
    ]
    pre_cutover_snapshot = ROOT / "artifacts" / "release" / "pre-cutover-snapshot.json"
    if pre_cutover_snapshot.is_file():
        critical.append(pre_cutover_snapshot)
    deployed_image_references: dict[str, str] = {}
    for path in deployment_receipts:
        payload = json.loads(path.read_text(encoding="utf-8"))
        deployed_image_references[path.stem.removesuffix("-identity")] = str(
            (payload.get("identity") or {}).get("image_reference") or ""
        )
    critical.extend(deployment_receipts)
    checksum_lines = []
    for path in critical:
        checksum_lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(ROOT).as_posix()}")
    (evidence_dir / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    repo_digests = sorted(image.get("RepoDigests") or [])
    immutable_reference = (
        deployed_image_references.get("production")
        or deployed_image_references.get("candidate")
        or (repo_digests[0] if repo_digests else "")
        or str(image.get("Id") or "")
    )
    receipt = {
        "schema_version": "smart-data-agent-release-evidence/v2",
        "commit_sha": sha,
        "image_reference": immutable_reference,
        "local_build_tag": args.image,
        "image_id": image.get("Id"),
        "target_platform": target_platform,
        "image_platform": image_platform,
        "image_variant": str(image.get("Variant") or ""),
        "repo_digests": repo_digests,
        "candidate_image_reference": deployed_image_references.get("candidate", ""),
        "production_image_reference": deployed_image_references.get("production", ""),
        "oci_revision": labels.get("org.opencontainers.image.revision"),
        "oci_created": labels.get("org.opencontainers.image.created"),
        "oci_source": source_url,
        "source_archive_sha256": identity.get("source_archive_sha256"),
        "dependency_lock_sha256": identity.get("dependency_lock_sha256"),
        "frontend_assets_sha256": identity.get("frontend_assets_sha256"),
        "release_toolchain_sha256": identity.get("release_toolchain_sha256"),
        "mysql_target_version": "8.0.18",
        "standard_id": "sda-production-development/v1",
        "sbom": sbom.relative_to(ROOT).as_posix(),
        "checksums": "SHA256SUMS",
    }
    if pre_cutover_snapshot.is_file():
        pre_cutover = json.loads(pre_cutover_snapshot.read_text(encoding="utf-8"))
        receipt["rollback_image_id"] = str((pre_cutover.get("rollback") or {}).get("image_id") or "")
        receipt["rollback_revision"] = str((pre_cutover.get("rollback") or {}).get("revision") or "")
    for source in (identity_path, gate_report_path, python_marker_path, *deployment_receipts, *([pre_cutover_snapshot] if pre_cutover_snapshot.is_file() else [])):
        shutil.copyfile(source, evidence_dir / source.name)
    (evidence_dir / "release-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "passed", "evidence_dir": str(evidence_dir), **receipt}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
