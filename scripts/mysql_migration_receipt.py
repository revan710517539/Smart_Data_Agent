#!/usr/bin/env python3
"""Create/verify the secret-free closure fields of a MySQL migration receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "smart-data-agent-mysql-migration-receipt/v1"
BASELINE = ROOT / "backend" / "platform" / "database" / "mysql" / "0001_production_schema.sql"
ADDITIVE = ROOT / "backend" / "platform" / "database" / "mysql" / "migrations"
MANIFEST = ROOT / "configs" / "deployment" / "mysql-migration-checksums.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def current_migration_closure() -> dict[str, str]:
    versions = sorted(
        path.stem.split("_", 1)[0]
        for path in ADDITIVE.glob("*.sql")
        if re.fullmatch(r"\d{4}", path.stem.split("_", 1)[0])
    )
    if not versions:
        raise ValueError("mysql_migration_receipt_additive_migrations_missing")
    return {
        "baseline_version": "0001",
        "baseline_checksum": _sha256(BASELINE),
        "latest_additive_version": versions[-1],
        "migration_manifest_sha256": _sha256(MANIFEST),
    }


def verify_migration_receipt(receipt_path: str | Path, commit_sha: str) -> dict[str, object]:
    expected_commit = str(commit_sha or "").strip()
    if re.fullmatch(r"[0-9a-f]{40}", expected_commit) is None:
        raise ValueError("mysql_migration_receipt_commit_sha_invalid")
    payload = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA:
        raise ValueError("mysql_migration_receipt_schema_invalid")
    if payload.get("status") != "passed":
        raise ValueError("mysql_migration_receipt_not_passed")
    if str(payload.get("commit_sha") or "") != expected_commit:
        raise ValueError("mysql_migration_receipt_commit_sha_mismatch")
    if str(payload.get("mysql_target_version") or "") != "8.0.18":
        raise ValueError("mysql_migration_receipt_mysql_version_mismatch")
    closure = current_migration_closure()
    for key, expected in closure.items():
        if str(payload.get(key) or "") != expected:
            raise ValueError(f"mysql_migration_receipt_{key}_mismatch")
    applied = payload.get("baseline_applied")
    execution_ms = payload.get("execution_ms")
    if not isinstance(applied, bool):
        raise ValueError("mysql_migration_receipt_baseline_applied_invalid")
    if not isinstance(execution_ms, int) or execution_ms < 0:
        raise ValueError("mysql_migration_receipt_execution_ms_invalid")
    return {
        "schema_version": SCHEMA,
        "commit_sha": expected_commit,
        "mysql_target_version": "8.0.18",
        **closure,
        "baseline_applied": applied,
        "execution_ms": execution_ms,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("verify", "closure"))
    parser.add_argument("receipt", nargs="?")
    parser.add_argument("--commit-sha", default="")
    args = parser.parse_args()
    try:
        if args.action == "closure":
            result: dict[str, object] = current_migration_closure()
        else:
            if not args.receipt:
                raise ValueError("mysql_migration_receipt_path_required")
            result = verify_migration_receipt(args.receipt, args.commit_sha)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"status": "passed", "receipt": result}, sort_keys=True))


if __name__ == "__main__":
    main()
