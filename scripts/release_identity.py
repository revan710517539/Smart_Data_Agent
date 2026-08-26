#!/usr/bin/env python3
"""Compute deterministic source, dependency and frontend release identities."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
IDENTITY_PATH = ROOT / "artifacts" / "release" / "release-identity.json"


def _sha256_parts(parts: Iterable[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for name, content in sorted(parts):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).digest())
        digest.update(b"\0")
    return digest.hexdigest()


def frontend_assets_hash(root: Path) -> str:
    if not root.is_dir():
        raise SystemExit("release_frontend_assets_missing")
    parts = [
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    ]
    if not parts:
        raise SystemExit("release_frontend_assets_empty")
    return _sha256_parts(parts)


def _git_archive_hash(sha: str) -> str:
    archive = subprocess.run(
        ["git", "archive", "--format=tar", sha],
        cwd=ROOT,
        capture_output=True,
    )
    if archive.returncode != 0:
        raise SystemExit("release_source_archive_failed")
    return hashlib.sha256(archive.stdout).hexdigest()


def _dependency_lock_hash() -> str:
    names = ("uv.lock", "package-lock.json", "requirements.lock", "requirements.runtime.lock")
    return _sha256_parts((name, (ROOT / name).read_bytes()) for name in names)


def _toolchain_hash() -> str:
    return _sha256_parts((
        ("configs/release/toolchain-lock.json", (ROOT / "configs/release/toolchain-lock.json").read_bytes()),
        ("Dockerfile.release-toolchain", (ROOT / "Dockerfile.release-toolchain").read_bytes()),
    ))


def _valid_sha(value: str) -> str:
    sha = value.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise SystemExit("release_identity_commit_sha_invalid")
    return sha


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    compute = subparsers.add_parser("compute")
    compute.add_argument("--commit-sha", required=True)
    compute.add_argument("--dist", default="dist")
    get = subparsers.add_parser("get")
    get.add_argument("key")
    frontend = subparsers.add_parser("frontend-hash")
    frontend.add_argument("path")
    args = parser.parse_args()

    if args.command == "frontend-hash":
        print(frontend_assets_hash((ROOT / args.path).resolve()))
        return
    if args.command == "compute":
        sha = _valid_sha(args.commit_sha)
        if subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip() != sha:
            raise SystemExit("release_identity_head_mismatch")
        payload = {
            "schema_version": "smart-data-agent-release-identity/v1",
            "commit_sha": sha,
            "source_archive_sha256": _git_archive_hash(sha),
            "dependency_lock_sha256": _dependency_lock_hash(),
            "frontend_assets_sha256": frontend_assets_hash((ROOT / args.dist).resolve()),
            "release_toolchain_sha256": _toolchain_hash(),
        }
        _write_json(IDENTITY_PATH, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    if args.command == "get":
        payload = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
        value = payload.get(args.key)
        if not isinstance(value, str) or not value:
            raise SystemExit(f"release_identity_key_missing:{args.key}")
        print(value)
        return
if __name__ == "__main__":
    main()
