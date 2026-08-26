from __future__ import annotations

import csv
import hashlib
import io
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


STATIC_WORKBOOK_VERSION = 1
STATIC_SHEET_VERSION = 1
STATIC_PATH_PREFIX = "static://"


class UnifiedRawTableSource:
    """Merge crawler deliveries with immutable uploaded workbook sheets.

    The database/object store remain authoritative for uploaded sheets.  A
    temporary verified CSV is materialized only when a batch engine requires a
    filesystem path; it is never treated as source data.
    """

    def __init__(self, crawler_source: Any, data_asset_store: Any, object_store: Any) -> None:
        self.crawler_source = crawler_source
        self.data_asset_store = data_asset_store
        self.object_store = object_store
        self._tenant_sources: dict[str, UnifiedTenantRawTableSource] = {}
        self._tenant_sources_lock = threading.RLock()

    def for_tenant(self, tenant_id: str) -> "UnifiedTenantRawTableSource":
        normalized = str(tenant_id or "").strip()
        crawler_source = self.crawler_source.for_tenant(normalized)
        with self._tenant_sources_lock:
            source = self._tenant_sources.get(normalized)
            if source is None or source.crawler_source is not crawler_source:
                source = UnifiedTenantRawTableSource(
                    normalized,
                    crawler_source,
                    self.data_asset_store,
                    self.object_store,
                )
                self._tenant_sources[normalized] = source
            return source

    def prime_catalog(self) -> None:
        self.crawler_source.prime_catalog()

    def read(self, relative_path: str) -> bytes:
        return self.crawler_source.read(relative_path)


class UnifiedTenantRawTableSource:
    def __init__(self, tenant_id: str, crawler_source: Any, data_asset_store: Any, object_store: Any) -> None:
        self.tenant_id = tenant_id
        self.crawler_source = crawler_source
        self.data_asset_store = data_asset_store
        self.object_store = object_store

    @property
    def catalog_ready(self) -> bool:
        return bool(getattr(self.crawler_source, "catalog_ready", True))

    @property
    def root(self) -> Any:
        return getattr(self.crawler_source, "root", None)

    def prime_catalog(self) -> None:
        self.crawler_source.prime_catalog()

    def table_assets(self, *, preview_limit: int = 10, force: bool = False) -> list[dict[str, Any]]:
        crawler_tables = self.crawler_source.table_assets(preview_limit=preview_limit, force=force)
        return [*crawler_tables, *self._static_tables(preview_limit)]

    def snapshot(self, *, force: bool = False) -> dict[str, Any]:
        crawler = self.crawler_source.snapshot(force=force)
        tables = self._static_tables(1)
        static_files = [
            {
                "relative_path": table["relativePath"],
                "file_name": table["fileName"],
                "size_bytes": int(table.get("sizeBytes") or 0),
                "modified_at": str(table.get("updatedAt") or ""),
                "content_hash": str(table.get("contentHash") or ""),
                "row_count": int(table.get("rowCount") or 0),
                "columns": [str(field.get("fieldNameCn") or "") for field in table.get("fields", [])],
                "source_kind": "static_workbook",
            }
            for table in tables
        ]
        return {
            **crawler,
            "mode": "unified_raw_tables",
            "source_read_only": True,
            "files": [*crawler.get("files", []), *static_files],
            "file_count": int(crawler.get("file_count") or 0) + len(static_files),
            "static_file_count": len(static_files),
        }

    def read(self, relative_path: str) -> bytes:
        table = self._static_table_for_path(relative_path)
        if table is None:
            return self.crawler_source.read(relative_path)
        return self.object_store.read(
            self.tenant_id,
            str(table.get("objectUri") or ""),
            str(table.get("contentHash") or ""),
        )

    def read_rows(self, relative_path: str, *, max_rows: int = 50_000) -> tuple[list[str], list[dict[str, str]]]:
        table = self._static_table_for_path(relative_path)
        if table is None:
            return self.crawler_source.read_rows(relative_path, max_rows=max_rows)
        content = self.read(relative_path).decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content, newline=""))
        headers = [str(header or "").strip() for header in (reader.fieldnames or [])]
        rows: list[dict[str, str]] = []
        for source_row in reader:
            if len(rows) >= max(1, min(int(max_rows), 50_000)):
                break
            rows.append({header: "" if source_row.get(header) is None else str(source_row.get(header)) for header in headers})
        return headers, rows

    def read_rows_matching_values(
        self,
        relative_path: str,
        *,
        key_field: str,
        values: list[str],
        max_matches: int = 20_000,
    ) -> tuple[list[str], list[dict[str, str]]]:
        table = self._static_table_for_path(relative_path)
        if table is None:
            return self.crawler_source.read_rows_matching_values(
                relative_path,
                key_field=key_field,
                values=values,
                max_matches=max_matches,
            )
        requested = {str(value or "").strip() for value in values if str(value or "").strip()}
        limit = max(1, min(int(max_matches), 50_000))
        if len(requested) > limit:
            raise ValueError("csv_source_match_limit_exceeded")
        content = self.read(relative_path).decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content, newline=""))
        headers = [str(header or "").strip() for header in (reader.fieldnames or [])]
        normalized_key = str(key_field or "").strip()
        if not normalized_key or normalized_key not in headers:
            raise ValueError("csv_source_match_key_missing")
        rows: list[dict[str, str]] = []
        found: set[str] = set()
        for source_row in reader:
            key = str(source_row.get(normalized_key) or "").strip()
            if not key or key not in requested:
                continue
            if key in found:
                raise ValueError("customer_segment_source_customer_key_duplicate")
            found.add(key)
            rows.append({header: "" if source_row.get(header) is None else str(source_row.get(header)) for header in headers})
            if len(found) == len(requested):
                break
        return headers, rows

    def resolve_path(self, relative_path: str) -> Path:
        table = self._static_table_for_path(relative_path)
        if table is None:
            return self.crawler_source.resolve_path(relative_path)
        content_hash = str(table.get("contentHash") or "")
        if not content_hash:
            raise ValueError("static_raw_table_content_hash_missing")
        tenant_key = hashlib.sha256(self.tenant_id.encode("utf-8")).hexdigest()[:16]
        directory = Path(tempfile.gettempdir()) / "smart-data-agent-static-raw" / tenant_key
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{content_hash}.csv"
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == content_hash:
            return target
        content = self.read(relative_path)
        temporary = directory / f".{content_hash}.{os.getpid()}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def _static_tables(self, preview_limit: int) -> list[dict[str, Any]]:
        if self.data_asset_store is None:
            return []
        tables: list[dict[str, Any]] = []
        for manifest in self.data_asset_store.list_bundle(self.tenant_id).get("raw_tables", []):
            if not isinstance(manifest, dict) or manifest.get("staticWorkbookVersion") != STATIC_WORKBOOK_VERSION:
                continue
            if str(manifest.get("lifecycleStatus") or "active") != "active":
                continue
            for sheet in manifest.get("sheets", []):
                if not isinstance(sheet, dict) or sheet.get("staticSheetVersion") != STATIC_SHEET_VERSION:
                    continue
                table = dict(sheet)
                table["previewRows"] = [dict(row) for row in table.get("previewRows", [])[:max(1, min(int(preview_limit), 50))]]
                table["fields"] = [dict(field) for field in table.get("fields", [])]
                tables.append(table)
        return sorted(tables, key=lambda item: (str(item.get("tableNameCn") or ""), str(item.get("id") or "")))

    def _static_table_for_path(self, relative_path: str) -> dict[str, Any] | None:
        requested = str(relative_path or "")
        if not requested.startswith(STATIC_PATH_PREFIX):
            return None
        return next((table for table in self._static_tables(1) if str(table.get("relativePath") or "") == requested), None)
