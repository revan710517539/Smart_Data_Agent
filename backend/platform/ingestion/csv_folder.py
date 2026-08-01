from __future__ import annotations

import csv
import hashlib
import io
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CSVFolderSource:
    """Read-only view of CSV files delivered to the project Origin_Data folder."""

    default_max_file_bytes = 128 * 1024 * 1024
    default_max_files = 500
    # Origin_Data is delivered in daily batches, not written by interactive
    # page traffic.  A short process-local cache avoids re-walking a mounted
    # folder (which can take seconds on macOS/network volumes) for every
    # data-management and analysis-picker request.  Scheduled processing
    # explicitly bypasses this cache before it transforms the daily delivery.
    default_catalog_cache_ttl_seconds = 60.0

    def __init__(
        self,
        root: str | Path,
        *,
        max_file_bytes: int = default_max_file_bytes,
        max_files: int = default_max_files,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.max_file_bytes = max(1, int(max_file_bytes))
        self.max_files = max(1, int(max_files))
        self._metadata_cache: dict[tuple[str, int, int], dict[str, Any]] = {}
        self._snapshot_cache: dict[str, Any] | None = None
        self._snapshot_cached_at = 0.0
        self._table_assets_cache: dict[int, list[dict[str, Any]]] = {}
        self._catalog_lock = threading.RLock()
        self._catalog_ready = threading.Event()

    @classmethod
    def from_environment(cls) -> "CSVFolderSource":
        # Smart Data Agent is a consumer of the project Origin_Data directory.
        # Every CSV below it is a read-only source table.
        root = Path(__file__).resolve().parents[3] / "Origin_Data"
        return cls(root)

    def prime_catalog(self) -> None:
        """Build the read-only catalog before the API begins serving traffic."""

        try:
            self.snapshot(force=True)
            self.table_assets(force=True)
        finally:
            self._catalog_ready.set()

    @property
    def catalog_ready(self) -> bool:
        return self._catalog_ready.is_set()

    def snapshot(self, *, force: bool = False) -> dict[str, Any]:
        with self._catalog_lock:
            if not force and self._snapshot_cache is not None and self._cache_is_fresh():
                return _copy_snapshot(self._snapshot_cache)
            snapshot = self._build_snapshot()
            self._snapshot_cache = snapshot
            self._snapshot_cached_at = time.monotonic()
            # The available source set may have changed; rebuild table views on
            # their next request rather than returning an obsolete table list.
            self._table_assets_cache.clear()
            return _copy_snapshot(snapshot)

    def _build_snapshot(self) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        if self.root.is_dir():
            for path in sorted(self.root.rglob("*.csv")):
                if len(candidates) >= self.max_files:
                    break
                if path.is_symlink() or not path.is_file():
                    continue
                try:
                    resolved = path.resolve()
                    resolved.relative_to(self.root)
                    stat = resolved.stat()
                    if stat.st_size > self.max_file_bytes:
                        continue
                    candidates.append(self._file_metadata(resolved, stat.st_mtime_ns, stat.st_size))
                except (OSError, UnicodeError, ValueError):
                    continue
        files, superseded = self._latest_files_only(candidates)
        return {
            "mode": "csv_folder",
            "source_read_only": True,
            "root": str(self.root),
            "available": self.root.is_dir(),
            "file_count": len(files),
            "files": files,
            "physical_file_count": len(candidates),
            "superseded_file_count": len(superseded),
            # Superseded deliveries remain read-only on disk for an explicit
            # archival/deletion policy, but cannot accidentally re-enter
            # data-management, self-analysis, or the daily topic batch.
            "selection_policy": "latest_per_source_identity",
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }

    def table_assets(self, *, preview_limit: int = 10, force: bool = False) -> list[dict[str, Any]]:
        """Return CSV files as stable, read-only raw-table assets.

        The frontend and self-analysis picker share this exact representation,
        preventing a configuration record from drifting away from the file it
        describes.  Only a bounded preview is returned; callers never receive
        an entire source file through the ordinary asset-list API.
        """

        normalized_limit = max(1, min(int(preview_limit), 50))
        with self._catalog_lock:
            snapshot = self.snapshot(force=force)
            cached = self._table_assets_cache.get(normalized_limit)
            if cached is not None and not force and self._cache_is_fresh():
                return _copy_table_assets(cached)
            tables: list[dict[str, Any]] = []
            for metadata in snapshot["files"]:
                try:
                    tables.append(self._table_asset(metadata, preview_limit=normalized_limit))
                except (OSError, UnicodeError, csv.Error, ValueError):
                    # A malformed file must not make the rest of the data catalog
                    # unavailable. It is simply omitted until its producer fixes it.
                    continue
            self._table_assets_cache[normalized_limit] = tables
            return _copy_table_assets(tables)

    def _cache_is_fresh(self) -> bool:
        return (time.monotonic() - self._snapshot_cached_at) < self.default_catalog_cache_ttl_seconds

    def read(self, relative_path: str) -> bytes:
        candidate = (self.root / str(relative_path)).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise PermissionError("csv_source_path_outside_root") from exc
        if candidate.is_symlink() or not candidate.is_file() or candidate.suffix.lower() != ".csv":
            raise FileNotFoundError("csv_source_file_not_found")
        if candidate.stat().st_size > self.max_file_bytes:
            raise ValueError("csv_source_file_too_large")
        return candidate.read_bytes()

    def read_rows(self, relative_path: str, *, max_rows: int = 50_000) -> tuple[list[str], list[dict[str, str]]]:
        """Read one protected CSV for a bounded internal transformation run."""

        content = self.read(relative_path)
        reader = csv.DictReader(io.StringIO(_decode_csv_text(content), newline=""))
        headers = [str(header or "").strip() for header in (reader.fieldnames or [])]
        if not any(headers):
            raise ValueError("csv_source_header_required")
        rows: list[dict[str, str]] = []
        for source_row in reader:
            if len(rows) >= max(1, min(int(max_rows), self.default_max_files * 1000)):
                break
            rows.append({header: "" if source_row.get(header) is None else str(source_row.get(header)) for header in headers})
        return headers, rows

    def _file_metadata(self, path: Path, modified_ns: int, size_bytes: int) -> dict[str, Any]:
        cache_key = (str(path), modified_ns, size_bytes)
        cached = self._metadata_cache.get(cache_key)
        if cached is not None:
            return dict(cached)
        content = path.read_bytes()
        text = _decode_csv_text(content)
        reader = csv.reader(io.StringIO(text, newline=""))
        header = next(reader, [])
        row_count = sum(1 for row in reader if row)
        metadata = {
            "relative_path": path.relative_to(self.root).as_posix(),
            "file_name": path.name,
            "size_bytes": size_bytes,
            "modified_at": datetime.fromtimestamp(
                modified_ns / 1_000_000_000,
                timezone.utc,
            ).isoformat(),
            "content_hash": hashlib.sha256(content).hexdigest(),
            "row_count": row_count,
            "columns": header,
        }
        self._metadata_cache = {
            key: value for key, value in self._metadata_cache.items() if key[0] != str(path)
        }
        self._metadata_cache[cache_key] = metadata
        return dict(metadata)

    def _table_asset(self, metadata: dict[str, Any], *, preview_limit: int) -> dict[str, Any]:
        relative_path = str(metadata["relative_path"])
        content = self.read(relative_path)
        text = _decode_csv_text(content)
        reader = csv.DictReader(io.StringIO(text, newline=""))
        headers = [str(header or "").strip() for header in (reader.fieldnames or [])]
        if not any(headers):
            raise ValueError("csv_source_header_required")
        used_headers: set[str] = set()
        normalized_headers: list[str] = []
        for index, header in enumerate(headers, start=1):
            base = header or f"field_{index}"
            candidate = base
            suffix = 2
            while candidate in used_headers:
                candidate = f"{base}_{suffix}"
                suffix += 1
            used_headers.add(candidate)
            normalized_headers.append(candidate)
        preview_rows: list[dict[str, str]] = []
        samples_by_header: dict[str, list[str]] = {header: [] for header in normalized_headers}
        non_empty_by_header: dict[str, int] = {header: 0 for header in normalized_headers}
        for row_number, row in enumerate(reader, start=1):
            normalized_row: dict[str, str] = {}
            for index, header in enumerate(normalized_headers):
                original_header = reader.fieldnames[index] if reader.fieldnames and index < len(reader.fieldnames) else header
                value = "" if row.get(original_header) is None else str(row.get(original_header)).strip()
                normalized_row[header] = value
                if value:
                    non_empty_by_header[header] += 1
                    if len(samples_by_header[header]) < 3:
                        samples_by_header[header].append(value)
            if len(preview_rows) < max(1, min(int(preview_limit), 50)):
                preview_rows.append(normalized_row)
        field_codes = _stable_field_codes(normalized_headers)
        fields = [
            {
                "fieldNameEn": field_codes[header],
                "fieldNameCn": header,
                "type": _infer_type(samples_by_header[header]),
                "explanation": _field_explanation(header, samples_by_header[header]),
                "isTime": _infer_type(samples_by_header[header]) in {"date", "datetime"},
                "isMetric": _infer_type(samples_by_header[header]) in {"integer", "decimal"},
                "notes": f"非空 {non_empty_by_header[header]}/{metadata['row_count']}；样例：{'、'.join(samples_by_header[header]) or '无'}",
                "exampleUsage": "只读 CSV 字段；可在智能分析中作为数据表上下文引用。",
            }
            for header in normalized_headers
        ]
        identity = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:24]
        display_name = Path(relative_path).stem
        return {
            "id": f"csv_{identity}",
            "tableNameEn": f"csv_{identity[:12]}",
            "tableNameCn": display_name,
            "source": "项目 Origin_Data 文件夹",
            "tableType": "csv_file",
            "primaryKey": _first_matching_code(field_codes, ("id", "编号", "主键", "流水")),
            "dateField": _first_matching_code(field_codes, ("date", "time", "日期", "时间")),
            "orgField": _first_matching_code(field_codes, ("org", "branch", "institution", "机构", "分行", "支行")),
            "customerField": _first_matching_code(field_codes, ("customer", "client", "客户")),
            "description": f"{relative_path} · CSV 原始数据，共 {metadata['row_count']} 行、{len(fields)} 个字段。",
            "updateFrequency": "随文件更新自动刷新",
            "restrictions": "项目 Origin_Data 文件夹内的只读 CSV；不支持页面爬取、外部连接或在线写入。",
            "exampleSql": f"-- CSV 文件：{relative_path}\nSELECT * FROM {f'csv_{identity[:12]}'} LIMIT 100;",
            "fields": fields,
            "updatedAt": metadata["modified_at"],
            "fileName": metadata["file_name"],
            "relativePath": relative_path,
            "rowCount": metadata["row_count"],
            "previewRows": preview_rows,
            "contentHash": metadata["content_hash"],
            "sourcePlatform": "本地CSV",
            "lifecycleStatus": "active",
            "assetVersion": 1,
            "schemaVersion": metadata["content_hash"][:16],
            "lockVersion": 1,
        }

    def _latest_files_only(self, files: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Choose the latest delivered CSV for each stable source identity.

        The independent collection process appends an ISO calendar date to its
        daily file names.  A date is a delivery version, not a distinct data
        table.  Period labels (``本月``, ``近7天`` etc.) remain part of the
        identity, so different business windows are never collapsed together.
        Files that have no date suffix are already their current delivery and
        stay visible unchanged.
        """

        newest_by_identity: dict[str, dict[str, Any]] = {}
        superseded: list[dict[str, Any]] = []
        for file in files:
            identity = _source_identity(str(file.get("relative_path") or ""))
            current = newest_by_identity.get(identity)
            if current is None or _newer_file(file, current):
                if current is not None:
                    superseded.append(current)
                newest_by_identity[identity] = file
            else:
                superseded.append(file)
        selected = sorted(newest_by_identity.values(), key=lambda item: str(item.get("relative_path") or ""))
        return selected, superseded


def _decode_csv_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeError("csv_source_text_encoding_unsupported")


def _copy_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return a shallowly cheap but caller-safe catalog projection."""

    return {
        **snapshot,
        "files": [
            {**item, "columns": list(item.get("columns") or [])}
            for item in snapshot.get("files", [])
        ],
    }


def _copy_table_assets(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Avoid exposing the cached mutable lists to route callers."""

    return [
        {
            **table,
            "fields": [dict(field) for field in table.get("fields", [])],
            "previewRows": [dict(row) for row in table.get("previewRows", [])],
        }
        for table in tables
    ]


def _source_identity(relative_path: str) -> str:
    path = Path(relative_path)
    # A collection delivery normally uses either `name2026-08-01.csv` or
    # `name_20260801.csv`. Strip only ISO-like date tokens; generic numbers
    # such as product codes are intentionally retained.
    stem = re.sub(r"(?<!\d)(?:19|20)\d{2}[-_.]?\d{2}[-_.]?\d{2}(?!\d)", "", path.stem)
    stem = re.sub(r"[_\-.\s]+", "_", stem).strip("_").casefold()
    return f"{path.parent.as_posix().casefold()}::{stem}"


def _newer_file(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_version = _delivery_date(str(left.get("file_name") or ""))
    right_version = _delivery_date(str(right.get("file_name") or ""))
    if left_version != right_version:
        return left_version > right_version
    left_modified = str(left.get("modified_at") or "")
    right_modified = str(right.get("modified_at") or "")
    if left_modified != right_modified:
        return left_modified > right_modified
    return str(left.get("relative_path") or "") > str(right.get("relative_path") or "")


def _delivery_date(file_name: str) -> str:
    matches = re.findall(r"(?<!\d)((?:19|20)\d{2})[-_.]?(\d{2})[-_.]?(\d{2})(?!\d)", file_name)
    return "".join(matches[-1]) if matches else ""


def _stable_field_codes(headers: list[str]) -> dict[str, str]:
    used: set[str] = set()
    result: dict[str, str] = {}
    for index, header in enumerate(headers, start=1):
        normalized = re.sub(r"[^A-Za-z0-9_]+", "_", header).strip("_")
        base = normalized if re.match(r"^[A-Za-z_]", normalized or "") else f"field_{index}"
        candidate = base[:190] or f"field_{index}"
        suffix = 2
        while candidate in used:
            candidate = f"{base[:180]}_{suffix}"
            suffix += 1
        used.add(candidate)
        result[header] = candidate
    return result


def _infer_type(samples: list[str]) -> str:
    if not samples:
        return "string"
    if all(value.casefold() in {"true", "false"} for value in samples):
        return "boolean"
    if all(re.fullmatch(r"[-+]?\d+", value.replace(",", "")) for value in samples):
        return "integer"
    if all(re.fullmatch(r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)", value.replace(",", "")) for value in samples):
        return "decimal"
    if all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) for value in samples):
        return "date"
    if all(re.fullmatch(r"\d{4}-\d{2}-\d{2}[T\s].*", value) for value in samples):
        return "datetime"
    return "string"


def _field_explanation(header: str, samples: list[str]) -> str:
    sample = "、".join(samples[:2]) or "无非空样例"
    return f"CSV 列“{header}”，自动识别；样例：{sample}。"


def _first_matching_code(field_codes: dict[str, str], tokens: tuple[str, ...]) -> str:
    for label, code in field_codes.items():
        haystack = f"{label} {code}".casefold()
        if any(token.casefold() in haystack for token in tokens):
            return code
    return ""
