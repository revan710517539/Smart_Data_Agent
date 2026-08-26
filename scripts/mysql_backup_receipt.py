#!/usr/bin/env python3
"""Validate a secret-free MySQL backup plus restore-test receipt."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


SCHEMA = "smart-data-agent-mysql-backup-receipt/v1"


def _timestamp(value: object, code: str) -> tuple[str, datetime]:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(code) from exc
    if parsed.tzinfo is None:
        raise ValueError(code)
    return text, parsed


def verify_backup_receipt(
    receipt_path: str | Path,
    *,
    max_age_seconds: int | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    receipt = Path(receipt_path).resolve(strict=True)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA:
        raise ValueError("mysql_backup_receipt_schema_invalid")
    created_at, created_time = _timestamp(payload.get("created_at"), "mysql_backup_receipt_created_at_invalid")
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    if str(source.get("mysql_version") or "").strip() != "8.0.18":
        raise ValueError("mysql_backup_receipt_version_mismatch")
    source_fingerprint = str(source.get("database_fingerprint_sha256") or "").strip()
    if re.fullmatch(r"[0-9a-f]{64}", source_fingerprint) is None:
        raise ValueError("mysql_backup_receipt_source_fingerprint_invalid")
    backup = payload.get("backup") if isinstance(payload.get("backup"), dict) else {}
    relative = str(backup.get("file") or "").strip()
    parsed_relative = PurePosixPath(relative)
    if not relative or parsed_relative.is_absolute() or ".." in parsed_relative.parts:
        raise ValueError("mysql_backup_receipt_file_invalid")
    backup_file = (receipt.parent / relative).resolve(strict=True)
    if not backup_file.is_relative_to(receipt.parent) or not backup_file.is_file():
        raise ValueError("mysql_backup_receipt_file_invalid")
    expected_size = backup.get("bytes")
    if not isinstance(expected_size, int) or expected_size <= 0 or backup_file.stat().st_size != expected_size:
        raise ValueError("mysql_backup_receipt_size_mismatch")
    expected_hash = str(backup.get("sha256") or "").strip()
    if re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
        raise ValueError("mysql_backup_receipt_hash_invalid")
    digest = hashlib.sha256()
    with backup_file.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_hash:
        raise ValueError("mysql_backup_receipt_hash_mismatch")
    restore = payload.get("restore_test") if isinstance(payload.get("restore_test"), dict) else {}
    if restore.get("status") != "passed" or str(restore.get("target") or "").strip() != "isolated":
        raise ValueError("mysql_backup_receipt_restore_test_required")
    restore_verified_at, restore_time = _timestamp(
        restore.get("verified_at"),
        "mysql_backup_receipt_restore_timestamp_invalid",
    )
    if restore_time < created_time:
        raise ValueError("mysql_backup_receipt_restore_precedes_backup")
    if max_age_seconds is not None:
        if not isinstance(max_age_seconds, int) or max_age_seconds <= 0:
            raise ValueError("mysql_backup_receipt_max_age_invalid")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("mysql_backup_receipt_now_invalid")
        age_seconds = (current - created_time).total_seconds()
        if age_seconds < -300:
            raise ValueError("mysql_backup_receipt_created_in_future")
        if age_seconds > max_age_seconds:
            raise ValueError("mysql_backup_receipt_expired")
    return {
        "schema_version": SCHEMA,
        "created_at": created_at,
        "mysql_version": "8.0.18",
        "database_fingerprint_sha256": source_fingerprint,
        "backup_file": relative,
        "backup_sha256": expected_hash,
        "backup_bytes": expected_size,
        "restore_verified_at": restore_verified_at,
        "restore_target": "isolated",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("verify",))
    parser.add_argument("receipt")
    parser.add_argument("--max-age-seconds", type=int)
    args = parser.parse_args()
    try:
        result = verify_backup_receipt(args.receipt, max_age_seconds=args.max_age_seconds)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"status": "passed", "receipt": result}, sort_keys=True))


if __name__ == "__main__":
    main()
