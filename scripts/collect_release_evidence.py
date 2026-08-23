#!/usr/bin/env python3
"""Create a secret-free evidence pack for an immutable Smart Data Agent image."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


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
    labels = ((image.get("Config") or {}).get("Labels") or {})
    if labels.get("org.opencontainers.image.revision") != sha:
        raise SystemExit("release_evidence_image_revision_mismatch")
    sbom = ROOT / "artifacts" / "sbom" / "smart-data-agent.cdx.json"
    if not sbom.is_file():
        raise SystemExit("release_evidence_sbom_missing")
    evidence_dir = ROOT / "artifacts" / "releases" / sha
    evidence_dir.mkdir(parents=True, exist_ok=True)
    critical = (
        ROOT / "Dockerfile",
        ROOT / "docker-compose.server.yml",
        ROOT / "DEVELOPMENT.md",
        ROOT / "configs" / "deployment" / "mysql-migration-checksums.json",
        sbom,
    )
    checksum_lines = []
    for path in critical:
        checksum_lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(ROOT).as_posix()}")
    (evidence_dir / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    receipt = {
        "schema_version": "smart-data-agent-release-evidence/v1",
        "commit_sha": sha,
        "image_reference": args.image,
        "image_id": image.get("Id"),
        "repo_digests": sorted(image.get("RepoDigests") or []),
        "oci_revision": labels.get("org.opencontainers.image.revision"),
        "oci_created": labels.get("org.opencontainers.image.created"),
        "mysql_target_version": "8.0.18",
        "standard_id": "sda-production-development/v1",
        "sbom": sbom.relative_to(ROOT).as_posix(),
        "checksums": "SHA256SUMS",
    }
    (evidence_dir / "release-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "passed", "evidence_dir": str(evidence_dir), **receipt}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
