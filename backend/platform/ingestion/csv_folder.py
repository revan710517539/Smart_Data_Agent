from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .crawler_manifest import CrawlerManifestError, resolve_crawler_tenant


_DELIVERY_TIMESTAMP_PREFIX_RE = re.compile(
    r"^(?P<year>(?:19|20)\d{2})(?P<month>\d{2})(?P<day>\d{2})"
    r"[_\-.]?(?P<time>\d{6})(?:[_\-.\s]+)(?P<title>.+)$"
)
_DELIVERY_DATE_TOKEN_RE = re.compile(
    r"(?<!\d)(?P<year>(?:19|20)\d{2})[-_.]?(?P<month>\d{2})[-_.]?(?P<day>\d{2})(?!\d)"
)


class CSVFolderSource:
    """Read-only view of one institution's Data Crawler delivery folder."""

    # The local Data Crawler checkout is the development delivery root.  It is
    # deliberately treated exactly like a deployed mount: callers must still
    # resolve an institution subdirectory through ``for_tenant``.  Production
    # must provide SMART_DATA_AGENT_DATA_CRAWLER_ROOT instead of relying on
    # this workstation-specific path.
    local_data_crawler_root = Path("/Users/revan/Documents/playwright/examples/data-crawler/data")
    container_data_crawler_root = Path("/app/data")

    default_max_file_bytes = 128 * 1024 * 1024
    default_max_files = 500
    # Data Crawler delivers daily batches, not interactive page traffic. A
    # short process-local cache avoids re-walking a mounted
    # folder (which can take seconds on macOS/network volumes) for every
    # data-management and analysis-picker request.  Scheduled processing
    # explicitly bypasses this cache before it transforms the daily delivery.
    default_catalog_cache_ttl_seconds = 60.0
    # Data Crawler keeps these operational artifacts for traceability, but they
    # are not business datasets and must never be offered to analysis users.
    auxiliary_directory_names = frozenset({"metadata", "系统验证"})
    auxiliary_file_markers = ("我的查询目录", "sql 编辑器运行", "sql 连通性验证", "采集链路健康检查")

    def __init__(
        self,
        root: str | Path,
        *,
        max_file_bytes: int = default_max_file_bytes,
        max_files: int = default_max_files,
        additional_roots: tuple[str | Path, ...] = (),
        catalog_root: str | Path | None = None,
        contract: dict[str, Any] | None = None,
        contract_error: str = "",
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self._catalog_root = Path(catalog_root).expanduser().resolve() if catalog_root else self.root
        roots = [self.root, *(Path(path).expanduser().resolve() for path in additional_roots)]
        self._roots = tuple(dict.fromkeys(roots))
        self.max_file_bytes = max(1, int(max_file_bytes))
        self.max_files = max(1, int(max_files))
        self._metadata_cache: dict[tuple[str, int, int], dict[str, Any]] = {}
        self._snapshot_cache: dict[str, Any] | None = None
        self._snapshot_cached_at = 0.0
        self._table_assets_cache: dict[int, list[dict[str, Any]]] = {}
        self._catalog_lock = threading.RLock()
        self._catalog_ready = threading.Event()
        self._tenant_sources: dict[str, "CSVFolderSource"] = {}
        self._contract = dict(contract or {})
        self._contract_error = str(contract_error or "")

    @classmethod
    def from_environment(cls) -> "CSVFolderSource":
        # A deployed Smart Data Agent reads the container mount directly from
        # /app/data/<机构名>. The workstation root is only the local analogue.
        # Neither path may fall back to legacy Origin_Data or another tenant.
        configured = str(os.getenv("SMART_DATA_AGENT_DATA_CRAWLER_ROOT") or "").strip()
        if configured:
            # An explicit server setting wins even while the path is not
            # mounted.  That state must fail closed as an empty tenant catalog,
            # rather than silently reading a local or legacy directory.
            root = Path(configured).expanduser()
        elif cls.container_data_crawler_root.is_dir() and (
            not cls.local_data_crawler_root.is_dir()
            or any(cls.container_data_crawler_root.iterdir())
        ):
            root = cls.container_data_crawler_root
        elif cls.local_data_crawler_root.is_dir():
            root = cls.local_data_crawler_root
        else:
            # Preserve the deployment contract even when neither mount has
            # arrived yet: the tenant catalog remains empty until /app/data is
            # mounted, never silently reverts to a legacy shared directory.
            root = cls.container_data_crawler_root
        return cls(root)

    def for_tenant(self, tenant_id: str) -> "CSVFolderSource":
        """Return the sole approved raw-data directory for one tenant.

        No fallback to the crawler root is permitted: if the institution folder
        is absent, the caller receives an empty catalog rather than another
        institution's files.
        """
        required_manifest = os.getenv("SMART_DATA_AGENT_ENV", "development").strip().lower() == "production"
        contract: dict[str, Any] | None = None
        contract_error = ""
        try:
            contract = resolve_crawler_tenant(self.root, str(tenant_id).strip(), required=required_manifest)
        except CrawlerManifestError as exc:
            contract_error = str(exc)
        # Data Crawler publishes business CSVs below the Chinese institution
        # name.  Its opaque English institution ID is only an API/catalog
        # identifier and must never become an SDA filesystem path.
        directory = tenant_directory_name(tenant_id)
        if contract and str(contract.get("institution_directory") or "").strip() != directory:
            contract_error = "crawler_tenant_directory_mismatch"
        if contract_error:
            directory = f".unmapped-{hashlib.sha256(str(tenant_id).encode('utf-8')).hexdigest()[:16]}"
        with self._catalog_lock:
            cache_key = f"{tenant_id}:{directory}:{contract_error}"
            source = self._tenant_sources.get(cache_key)
            if source is None:
                source = CSVFolderSource(
                    self.root / directory,
                    max_file_bytes=self.max_file_bytes,
                    max_files=self.max_files,
                    # A versioned production manifest is the complete delivery
                    # boundary. Legacy source-id folders remain a development
                    # compatibility path only and cannot widen that boundary.
                    additional_roots=() if contract else self._crawler_source_roots(directory),
                    catalog_root=self.root,
                    contract=contract,
                    contract_error=contract_error,
                )
                self._tenant_sources[cache_key] = source
                threading.Thread(target=source.prime_catalog, name=f"csv-catalog-{directory}", daemon=True).start()
            return source

    def _crawler_source_roots(self, directory: str) -> tuple[Path, ...]:
        """Resolve legacy source-id delivery folders from Crawler metadata.

        Current Crawler writes business CSVs to ``/<机构名>``. Older or
        partially upgraded runs can still publish to ``/csv/<source-id>``.
        The source registry is the authority that binds those opaque folders
        to one institution; no unscoped ``/csv`` fallback is permitted.
        """

        institution_id = _crawler_institution_id(directory)
        metadata_path = self.root / "metadata" / "sources.json"
        if not institution_id or not metadata_path.is_file():
            return ()
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return ()
        items = payload.get("items") if isinstance(payload, dict) else []
        if not isinstance(items, list):
            return ()
        source_ids = [
            str(item.get("id") or "").strip()
            for item in items
            if isinstance(item, dict) and str(item.get("institutionId") or "").strip() == institution_id
        ]
        return tuple(
            self.root / "csv" / source_id
            for source_id in source_ids
            if re.fullmatch(r"[A-Za-z0-9_-]{1,100}", source_id)
        )

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

    def wait_until_ready(self, timeout: float = 30.0) -> bool:
        return self._catalog_ready.wait(timeout=max(0.0, float(timeout)))

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
        source_root_exists = False
        source_permission_denied = False
        manifest_files = {
            str(item.get("path") or "").strip()
            for item in self._contract.get("files", [])
            if isinstance(item, dict) and str(item.get("path") or "").strip()
        }
        for source_root in self._roots:
            if not source_root.is_dir():
                continue
            source_root_exists = True
            if not os.access(source_root, os.R_OK | os.X_OK):
                source_permission_denied = True
                continue
            try:
                paths = sorted(source_root.rglob("*.csv"))
            except (OSError, PermissionError):
                source_permission_denied = True
                continue
            for path in paths:
                if len(candidates) >= self.max_files:
                    break
                if path.is_symlink() or not path.is_file():
                    continue
                try:
                    resolved = path.resolve()
                    if not any(resolved == root or root in resolved.parents for root in self._roots):
                        continue
                    if manifest_files and self._relative_path(resolved) not in manifest_files:
                        continue
                    if self._is_auxiliary_artifact(resolved):
                        continue
                    stat = resolved.stat()
                    if stat.st_size > self.max_file_bytes:
                        continue
                    candidates.append(self._file_metadata(resolved, stat.st_mtime_ns, stat.st_size))
                except PermissionError:
                    source_permission_denied = True
                    continue
                except (OSError, UnicodeError, ValueError):
                    continue
        files, superseded = self._latest_files_only(candidates)
        source_available = source_root_exists and not source_permission_denied
        source_error = (
            self._contract_error
            or ("source_permission_denied" if source_permission_denied else "")
            or ("source_root_missing" if not source_root_exists else "")
            or ("no_files" if not files else "")
        )
        return {
            "mode": "csv_folder",
            "source_read_only": True,
            "root": str(self.root),
            "available": source_available,
            "file_count": len(files),
            "files": files,
            "physical_file_count": len(candidates),
            "superseded_file_count": len(superseded),
            # Superseded deliveries remain read-only on disk for an explicit
            # archival/deletion policy, but cannot accidentally re-enter
            # data-management, self-analysis, or the daily topic batch.
            "selection_policy": "latest_per_source_identity",
            "contract_status": "invalid" if self._contract_error else "validated" if self._contract else "legacy_local",
            "contract_error": source_error,
            "tenant_id": str(self._contract.get("tenant_id") or ""),
            "institution_directory": str(self._contract.get("institution_directory") or self.root.name),
            "manifest_schema_version": str(self._contract.get("schema_version") or ""),
            "tenant_schema_version": str(self._contract.get("tenant_schema_version") or ""),
            "manifest_generated_at": str(self._contract.get("generated_at") or ""),
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }

    def _is_auxiliary_artifact(self, path: Path) -> bool:
        """Exclude Data Crawler control receipts from the analysis catalog."""
        relative_path = Path(self._relative_path(path))
        directory_names = {part.casefold() for part in relative_path.parts[:-1]}
        if directory_names & {name.casefold() for name in self.auxiliary_directory_names}:
            return True
        normalized_name = path.stem.casefold()
        return any(marker.casefold() in normalized_name for marker in self.auxiliary_file_markers)

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
        return self.resolve_path(relative_path).read_bytes()

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve one catalog path within this tenant's approved roots."""

        requested = str(relative_path)
        candidates = tuple(dict.fromkeys(((self.root / requested).resolve(), (self._catalog_root / requested).resolve())))
        allowed_candidate_seen = False
        for candidate in candidates:
            if not any(candidate == root or root in candidate.parents for root in self._roots):
                continue
            allowed_candidate_seen = True
            if candidate.is_symlink() or not candidate.is_file() or candidate.suffix.lower() != ".csv":
                continue
            if candidate.stat().st_size > self.max_file_bytes:
                raise ValueError("csv_source_file_too_large")
            return candidate
        if not allowed_candidate_seen:
            raise PermissionError("csv_source_path_outside_root")
        raise FileNotFoundError("csv_source_file_not_found")

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

    def read_rows_matching_values(
        self,
        relative_path: str,
        *,
        key_field: str,
        values: list[str],
        max_matches: int = 20_000,
    ) -> tuple[list[str], list[dict[str, str]]]:
        """Scan the complete bounded source while retaining only requested keys.

        Customer-list analysis cannot sample the first N rows: a requested
        customer may occur anywhere in the authoritative CSV.  The file size
        limit remains the capacity boundary and only matching rows are kept in
        memory.
        """

        requested = {str(value or "").strip() for value in values if str(value or "").strip()}
        limit = max(1, min(int(max_matches), 50_000))
        if len(requested) > limit:
            raise ValueError("csv_source_match_limit_exceeded")
        content = self.read(relative_path)
        reader = csv.DictReader(io.StringIO(_decode_csv_text(content), newline=""))
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
            "relative_path": self._relative_path(path),
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

    def _relative_path(self, path: Path) -> str:
        resolved = path.resolve()
        if resolved == self.root or self.root in resolved.parents:
            return resolved.relative_to(self.root).as_posix()
        for source_root in self._roots[1:]:
            if resolved == source_root or source_root in resolved.parents:
                return resolved.relative_to(self._catalog_root).as_posix()
        raise PermissionError("csv_source_path_outside_root")

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
        # Delivery filenames change daily.  External-reference consent belongs
        # to the logical source, never to one immutable delivery file.
        source_key = hashlib.sha256(_source_identity(relative_path).encode("utf-8")).hexdigest()[:32]
        schema_fingerprint = hashlib.sha256(
            "|".join(f"{field_codes[header]}:{_infer_type(samples_by_header[header])}" for header in normalized_headers).encode("utf-8")
        ).hexdigest()[:32]
        display_name = _display_table_name(relative_path)
        return {
            "id": f"csv_{identity}",
            "tableNameEn": f"csv_{identity[:12]}",
            "tableNameCn": display_name,
            "source": "当前机构 Data Crawler 文件夹",
            "tableType": "csv_file",
            "primaryKey": _first_matching_code(field_codes, ("id", "编号", "主键", "流水")),
            "dateField": _first_matching_code(field_codes, ("date", "time", "日期", "时间")),
            "orgField": _first_matching_code(field_codes, ("org", "branch", "institution", "机构", "分行", "支行")),
            "customerField": _first_matching_code(field_codes, ("customer", "client", "客户")),
            "description": f"{relative_path} · CSV 原始数据，共 {metadata['row_count']} 行、{len(fields)} 个字段。",
            "updateFrequency": "随文件更新自动刷新",
            "restrictions": "当前机构 Data Crawler 文件夹内的只读 CSV；不支持页面爬取、外部连接或在线写入。",
            "exampleSql": f"-- CSV 文件：{relative_path}\nSELECT * FROM {f'csv_{identity[:12]}'} LIMIT 100;",
            "fields": fields,
            "updatedAt": metadata["modified_at"],
            "fileName": metadata["file_name"],
            "relativePath": relative_path,
            "sourceKey": source_key,
            "schemaFingerprint": schema_fingerprint,
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


def tenant_directory_name(tenant_id: str) -> str:
    """Map the authenticated tenant code to one safe crawler directory name."""
    name = str(tenant_id or "").strip().split(":", 1)[-1].strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name or "\x00" in name:
        raise ValueError("csv_source_tenant_directory_invalid")
    return name


def _crawler_institution_id(directory: str) -> str:
    return {
        "华兴银行": "huaxing",
        "郑州银行": "zhengzhou",
        "广州银行": "guangzhou",
        "南京银行": "nanjing",
        "石嘴山银行": "shizuishan",
        "兰州银行": "lanzhou",
        "临商银行": "linshang",
        "瑞丰银行": "ruifeng",
        "兴业消金": "xingye-consumer-finance",
        "汉口银行": "hankou",
    }.get(directory, "")


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


def _display_table_name(relative_path: str) -> str:
    """Project an immutable delivery filename as ``题目_YYYY-MM-DD``."""

    title, delivery_date = _delivery_name_parts(relative_path)
    return f"{title}_{delivery_date}" if delivery_date else title


def _delivery_name_parts(relative_path: str) -> tuple[str, str]:
    path = Path(relative_path)
    stem = path.stem.strip()
    timestamp_match = _DELIVERY_TIMESTAMP_PREFIX_RE.fullmatch(stem)
    if timestamp_match is not None:
        title = _clean_delivery_title(timestamp_match.group("title"))
        if title:
            return title, _normalized_delivery_date(timestamp_match)

    date_matches = list(_DELIVERY_DATE_TOKEN_RE.finditer(stem))
    if date_matches:
        date_match = date_matches[-1]
        title = _clean_delivery_title(f"{stem[:date_match.start()]}{stem[date_match.end():]}")
        if title:
            return title, _normalized_delivery_date(date_match)

    parent_date_match = _DELIVERY_DATE_TOKEN_RE.fullmatch(path.parent.name)
    if parent_date_match is not None:
        title = _clean_delivery_title(stem)
        if title:
            return title, _normalized_delivery_date(parent_date_match)
    return stem, ""


def _clean_delivery_title(value: str) -> str:
    title = str(value or "").strip().strip("_-. ")
    return re.sub(r"[_\-.\s]{2,}", "_", title).strip("_")


def _normalized_delivery_date(match: re.Match[str]) -> str:
    return f"{match.group('year')}-{match.group('month')}-{match.group('day')}"


def _source_identity(relative_path: str) -> str:
    path = Path(relative_path)
    # The physical file may be `YYYYMMDD_HHMMSS_题目.csv`, `YYYYMMDD_题目.csv`
    # or `题目_YYYY-MM-DD.csv`. The run timestamp and calendar date are delivery
    # versions, not part of the logical source identity.
    stem, _delivery_version = _delivery_name_parts(relative_path)
    stem = re.sub(r"[_\-.\s]+", "_", stem).strip("_").casefold()
    parent = path.parent
    if len(path.parts) >= 4 and path.parts[0].casefold() == "csv" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.parts[-2]):
        parent = Path(*path.parts[:-2])
    return f"{parent.as_posix().casefold()}::{stem}"


def _newer_file(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_version = _delivery_date(str(left.get("relative_path") or left.get("file_name") or ""))
    right_version = _delivery_date(str(right.get("relative_path") or right.get("file_name") or ""))
    if left_version != right_version:
        return left_version > right_version
    left_modified = str(left.get("modified_at") or "")
    right_modified = str(right.get("modified_at") or "")
    if left_modified != right_modified:
        return left_modified > right_modified
    return str(left.get("relative_path") or "") > str(right.get("relative_path") or "")


def _delivery_date(file_name: str) -> str:
    _title, delivery_date = _delivery_name_parts(file_name)
    return delivery_date.replace("-", "")


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
    if all(
        re.fullmatch(r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?:%|万|亿)", value.replace(",", ""))
        for value in samples
    ):
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
