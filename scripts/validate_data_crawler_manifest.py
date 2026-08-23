#!/usr/bin/env python3
"""Validate the versioned, read-only Data Crawler delivery contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.platform.ingestion.crawler_manifest import (  # noqa: E402
    MANIFEST_SCHEMA_VERSION,
    resolve_crawler_tenant,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/app/data"))
    parser.add_argument("--tenant-id", action="append", default=[])
    parser.add_argument("--require-read-only", action="store_true")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise SystemExit("crawler_manifest_schema_incompatible")
    declared = [
        str(item.get("tenant_id") or "").strip()
        for item in payload.get("tenants", [])
        if isinstance(item, dict) and str(item.get("tenant_id") or "").strip()
    ]
    requested = args.tenant_id or declared
    if not requested:
        raise SystemExit("crawler_manifest_has_no_tenants")
    resolved = [resolve_crawler_tenant(root, tenant_id, required=True) for tenant_id in requested]
    if args.require_read_only and not _mount_is_read_only(root):
        raise SystemExit("crawler_mount_is_not_read_only")
    print(json.dumps({
        "status": "passed",
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "tenant_count": len(resolved),
        "file_count": sum(len(item.get("files") or []) for item in resolved if item),
        "read_only": _mount_is_read_only(root),
    }, sort_keys=True))


def _mount_is_read_only(path: Path) -> bool:
    mountinfo = Path("/proc/self/mountinfo")
    if not mountinfo.is_file():
        return False
    candidates: list[tuple[int, set[str]]] = []
    for line in mountinfo.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) < 6:
            continue
        mount_point = Path(fields[4].replace("\\040", " "))
        try:
            path.relative_to(mount_point)
        except ValueError:
            continue
        candidates.append((len(mount_point.parts), set(fields[5].split(","))))
    return bool(candidates and "ro" in max(candidates, key=lambda item: item[0])[1])


if __name__ == "__main__":
    main()
