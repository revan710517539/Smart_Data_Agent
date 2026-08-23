#!/usr/bin/env python3
"""Fail closed when a migration published in a Git baseline is changed or removed."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
MYSQL_ROOT = ROOT / "backend" / "platform" / "database" / "mysql"
MYSQL_PREFIX = "backend/platform/database/mysql/"


def _git(*args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or f"git_command_failed:{' '.join(args)}")
    return completed.stdout


def _version(path: str) -> str:
    name = Path(path).name
    version = name.split("_", 1)[0]
    if not version.isdigit():
        raise SystemExit(f"mysql_migration_filename_invalid:{path}")
    return version


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", default=os.getenv("SMART_DATA_AGENT_MIGRATION_BASE_REF", "HEAD"))
    args = parser.parse_args()
    base_ref = str(args.base_ref or "").strip()
    if not base_ref or set(base_ref) == {"0"}:
        raise SystemExit("mysql_migration_base_ref_required")
    _git("cat-file", "-e", f"{base_ref}^{{commit}}")
    baseline_paths = [
        path.strip()
        for path in _git("ls-tree", "-r", "--name-only", base_ref, MYSQL_PREFIX.rstrip("/")).splitlines()
        if path.strip().endswith(".sql")
    ]
    current_paths = sorted(
        f"{MYSQL_PREFIX}{path.relative_to(MYSQL_ROOT).as_posix()}"
        for path in MYSQL_ROOT.rglob("*.sql")
    )
    errors: list[str] = []
    for path in baseline_paths:
        current = ROOT / path
        if not current.is_file():
            errors.append(f"published_migration_removed:{path}")
            continue
        baseline = subprocess.run(["git", "show", f"{base_ref}:{path}"], cwd=ROOT, capture_output=True)
        if baseline.returncode != 0:
            errors.append(f"published_migration_unreadable:{path}")
            continue
        if hashlib.sha256(current.read_bytes()).digest() != hashlib.sha256(baseline.stdout).digest():
            errors.append(f"published_migration_modified:{path}")
    baseline_versions = {_version(path) for path in baseline_paths}
    current_versions = [_version(path) for path in current_paths]
    if len(current_versions) != len(set(current_versions)):
        errors.append("mysql_migration_version_duplicate")
    max_baseline = max(baseline_versions, default="0000")
    for path in sorted(set(current_paths) - set(baseline_paths)):
        if _version(path) <= max_baseline:
            errors.append(f"new_migration_version_not_append_only:{path}")
    result = {
        "status": "passed" if not errors else "failed",
        "base_ref": base_ref,
        "published_count": len(baseline_paths),
        "current_count": len(current_paths),
        "errors": errors,
    }
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
