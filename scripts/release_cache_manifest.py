#!/usr/bin/env python3
"""Create or verify a content-addressed release dependency cache."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "smart-data-agent-release-cache/v1"
MANIFEST_NAME = "release-cache-manifest.json"
CACHE_DIRECTORIES = ("npm", "uv", "wheelhouse")
LOCK_FILES = (
    "package-lock.json",
    "uv.lock",
    "requirements.lock",
    "requirements.runtime.lock",
    "configs/release/toolchain-lock.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_files(cache_root: Path) -> list[Path]:
    files: list[Path] = []
    for directory in CACHE_DIRECTORIES:
        target = cache_root / directory
        if not target.is_dir():
            raise SystemExit(f"release_cache_directory_missing:{directory}")
        files.extend(path for path in target.rglob("*") if path.is_file())
    return sorted(files, key=lambda path: path.relative_to(cache_root).as_posix())


def _lock_contract() -> dict[str, str]:
    return {name: _sha256(ROOT / name) for name in LOCK_FILES}


def create_manifest(cache_root: Path) -> dict[str, object]:
    files = _cache_files(cache_root)
    if not files:
        raise SystemExit("release_cache_empty")
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "locks": _lock_contract(),
        "files": [
            {
                "path": path.relative_to(cache_root).as_posix(),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in files
        ],
    }
    manifest = cache_root / MANIFEST_NAME
    temporary = manifest.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(manifest)
    return payload


def verify_manifest(cache_root: Path, expected_manifest_sha256: str) -> dict[str, object]:
    expected = str(expected_manifest_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise SystemExit("release_cache_manifest_sha256_invalid")
    manifest = cache_root / MANIFEST_NAME
    if not manifest.is_file():
        raise SystemExit("release_cache_manifest_missing")
    if _sha256(manifest) != expected:
        raise SystemExit("release_cache_manifest_digest_mismatch")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit("release_cache_manifest_invalid_json") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit("release_cache_manifest_schema_invalid")
    if payload.get("locks") != _lock_contract():
        raise SystemExit("release_cache_lock_contract_mismatch")
    entries = payload.get("files")
    if not isinstance(entries, list) or not entries:
        raise SystemExit("release_cache_manifest_files_required")
    declared: dict[str, dict[str, object]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit("release_cache_manifest_file_invalid")
        relative = str(entry.get("path") or "")
        path = Path(relative)
        if not relative or path.is_absolute() or ".." in path.parts or path.parts[0] not in CACHE_DIRECTORIES:
            raise SystemExit("release_cache_manifest_file_path_invalid")
        if relative in declared:
            raise SystemExit("release_cache_manifest_file_duplicate")
        if not isinstance(entry.get("size"), int) or int(entry["size"]) < 0:
            raise SystemExit("release_cache_manifest_file_size_invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256") or "")):
            raise SystemExit("release_cache_manifest_file_sha256_invalid")
        declared[relative] = entry
    actual_files = _cache_files(cache_root)
    actual_names = {path.relative_to(cache_root).as_posix() for path in actual_files}
    if actual_names != set(declared):
        raise SystemExit("release_cache_manifest_inventory_mismatch")
    for path in actual_files:
        relative = path.relative_to(cache_root).as_posix()
        entry = declared[relative]
        if path.stat().st_size != entry["size"] or _sha256(path) != entry["sha256"]:
            raise SystemExit(f"release_cache_file_digest_mismatch:{relative}")
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_sha256": expected,
        "file_count": len(actual_files),
        "locks": payload["locks"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("cache_root")
    verify = subparsers.add_parser("verify")
    verify.add_argument("cache_root")
    verify.add_argument("expected_manifest_sha256")
    args = parser.parse_args()
    cache_root = Path(args.cache_root).expanduser().resolve()
    if args.command == "create":
        payload = create_manifest(cache_root)
        print(json.dumps({"status": "created", **payload}, ensure_ascii=False, sort_keys=True))
        return
    result = verify_manifest(cache_root, args.expected_manifest_sha256)
    print(json.dumps({"status": "passed", **result}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
