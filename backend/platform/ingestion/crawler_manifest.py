from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


MANIFEST_SCHEMA_VERSION = "smart-data-crawler-manifest/v1"


class CrawlerManifestError(ValueError):
    pass


def resolve_crawler_tenant(root: Path, tenant_id: str, *, required: bool) -> dict[str, Any] | None:
    manifest_path = _manifest_path(root)
    if not manifest_path.is_file():
        if required:
            raise CrawlerManifestError("crawler_manifest_missing")
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CrawlerManifestError("crawler_manifest_invalid_json") from exc
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise CrawlerManifestError("crawler_manifest_schema_incompatible")
    if not str(payload.get("generated_at") or "").strip():
        raise CrawlerManifestError("crawler_manifest_generated_at_required")
    tenants = payload.get("tenants")
    if not isinstance(tenants, list):
        raise CrawlerManifestError("crawler_manifest_tenants_required")
    tenant_ids: list[str] = []
    directories: list[str] = []
    for item in tenants:
        if not isinstance(item, dict):
            raise CrawlerManifestError("crawler_manifest_tenant_invalid")
        declared_tenant = str(item.get("tenant_id") or "").strip()
        declared_directory = str(item.get("institution_directory") or "").strip()
        if not declared_tenant:
            raise CrawlerManifestError("crawler_manifest_tenant_id_required")
        if not declared_directory:
            raise CrawlerManifestError("crawler_tenant_directory_invalid")
        tenant_ids.append(declared_tenant)
        directories.append(declared_directory)
    if len(tenant_ids) != len(set(tenant_ids)):
        raise CrawlerManifestError("crawler_tenant_directory_mapping_duplicate")
    if len(directories) != len(set(directories)):
        raise CrawlerManifestError("crawler_institution_directory_duplicate")
    matches = [item for item in tenants if isinstance(item, dict) and str(item.get("tenant_id") or "").strip() == tenant_id]
    if len(matches) != 1:
        raise CrawlerManifestError("crawler_tenant_directory_mapping_missing" if not matches else "crawler_tenant_directory_mapping_duplicate")
    entry = dict(matches[0])
    directory = str(entry.get("institution_directory") or "").strip()
    if not directory or directory in {".", ".."} or "/" in directory or "\\" in directory:
        raise CrawlerManifestError("crawler_tenant_directory_invalid")
    schema_version = str(entry.get("schema_version") or "").strip()
    if not schema_version:
        raise CrawlerManifestError("crawler_tenant_schema_version_required")
    files = entry.get("files")
    if not isinstance(files, list):
        raise CrawlerManifestError("crawler_manifest_files_required")
    file_paths = [str(item.get("path") or "").strip() for item in files if isinstance(item, dict)]
    if len(file_paths) != len(files) or len(file_paths) != len(set(file_paths)):
        raise CrawlerManifestError("crawler_manifest_file_duplicate")
    tenant_root = (root / directory).resolve()
    if root.resolve() not in tenant_root.parents:
        raise CrawlerManifestError("crawler_tenant_directory_outside_root")
    for item in files:
        _validate_manifest_file(tenant_root, item)
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": str(payload["generated_at"]),
        "tenant_id": tenant_id,
        "institution_directory": directory,
        "tenant_schema_version": schema_version,
        "files": [dict(item) for item in files if isinstance(item, dict)],
    }


def _manifest_path(root: Path) -> Path:
    configured = os.getenv("SMART_DATA_AGENT_DATA_CRAWLER_MANIFEST", "").strip()
    candidate = Path(configured).expanduser().resolve() if configured else (root / "manifest.json").resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise CrawlerManifestError("crawler_manifest_outside_root")
    return candidate


def _validate_manifest_file(tenant_root: Path, item: Any) -> None:
    if not isinstance(item, dict):
        raise CrawlerManifestError("crawler_manifest_file_invalid")
    relative = str(item.get("path") or "").strip()
    checksum = str(item.get("sha256") or "").strip().lower()
    if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise CrawlerManifestError("crawler_manifest_file_path_invalid")
    if Path(relative).suffix.casefold() != ".csv":
        raise CrawlerManifestError("crawler_manifest_file_type_invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise CrawlerManifestError("crawler_manifest_file_sha256_invalid")
    target = (tenant_root / relative).resolve()
    if tenant_root != target and tenant_root not in target.parents:
        raise CrawlerManifestError("crawler_manifest_file_outside_tenant")
    if not target.is_file():
        raise CrawlerManifestError("crawler_manifest_file_missing")
    if hashlib.sha256(target.read_bytes()).hexdigest() != checksum:
        raise CrawlerManifestError("crawler_manifest_file_checksum_mismatch")
