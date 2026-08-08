from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import threading
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TopicDataStore:
    """Filesystem-backed data snapshots for self-analysis and topic tables.

    ``Origin_Data`` is read-only input. This store is the only writer below
    ``Topic_Data``: every completed analysis owns a history folder, configured
    shortcuts own their latest result folder, saved reports own one current
    result folder, and every topic table has one current calculated-result
    folder.
    """

    max_inline_rows = 200
    max_rows_per_snapshot = 50_000
    schema_version = 1

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._ensure_within_root(self.root)
        # A single process can execute several self-analysis tasks in parallel.
        # The index is a read-modify-write document, so protect that sequence
        # rather than merely relying on atomic rename of the final file.
        self._index_lock = threading.RLock()

    def record_analysis_execution(
        self,
        *,
        tenant_id: str,
        user_id: str,
        task: dict[str, Any],
        source_reference: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_id = _required_text(task.get("task_id"), "analysis_task_id")
        result = _first_result(task)
        data_rows = _rows(result.get("data"))
        manifest = self._analysis_manifest(task, result, data_rows)
        history_dir = self._history_dir(tenant_id, user_id, task_id)
        self._write_snapshot(history_dir, manifest, data_rows, data_rows)
        history_ref = self._reference_payload("history", task_id, history_dir, manifest)
        self._update_index(tenant_id, user_id, "history", task_id, history_ref)

        source = source_reference if isinstance(source_reference, dict) else {}
        if str(source.get("type") or "") == "shortcut" and str(source.get("id") or "").strip():
            shortcut_id = str(source["id"]).strip()
            shortcut_dir = self._shortcut_dir(tenant_id, user_id, shortcut_id)
            shortcut_manifest = {**manifest, "source_reference": {"type": "shortcut", "id": shortcut_id}}
            self._write_snapshot(shortcut_dir, shortcut_manifest, data_rows, data_rows)
            shortcut_ref = self._reference_payload("shortcut", shortcut_id, shortcut_dir, shortcut_manifest)
            self._update_index(tenant_id, user_id, "shortcut", shortcut_id, shortcut_ref)
        else:
            shortcut_ref = None

        return {"history": history_ref, "shortcut": shortcut_ref}

    def record_topic_table_snapshot(
        self,
        *,
        tenant_id: str,
        user_id: str,
        topic_table_id: str,
        task: dict[str, Any],
    ) -> dict[str, Any]:
        task_id = _required_text(task.get("task_id"), "analysis_task_id")
        result = _first_result(task)
        data_rows = _rows(result.get("data"))
        version_id = "current"
        version_dir = self._topic_current_dir(tenant_id, topic_table_id)
        manifest = {
            **self._analysis_manifest(task, result, data_rows),
            "topic_table_id": topic_table_id,
            "version_id": version_id,
            "source_reference": {"type": "topic", "id": topic_table_id},
        }
        self._write_snapshot(version_dir, manifest, data_rows, data_rows)
        ref = self._reference_payload("topic", topic_table_id, version_dir, manifest)
        self._update_index(tenant_id, user_id, "topic", topic_table_id, ref)
        return ref

    def record_topic_table_result(
        self,
        *,
        tenant_id: str,
        user_id: str,
        topic_table_id: str,
        sql: str,
        rows: list[dict[str, Any]],
        source: str = "topic_batch",
    ) -> dict[str, Any]:
        directory = self._topic_current_dir(tenant_id, topic_table_id)
        manifest = {
            "schema_version": self.schema_version,
            "created_at": _utc_now(),
            "task_id": "",
            "execution_id": "",
            "question": "主题表定时加工",
            "status": "completed",
            "summary": "主题表已按最新 Origin_Data 文件重新计算。",
            "sql": str(sql or ""),
            "python_script": "",
            "evidence_id": "",
            "row_count": len(rows),
            "columns": _columns(rows),
            "data_sha256": _rows_hash(rows),
            "topic_table_id": topic_table_id,
            "version_id": "current",
            "source_reference": {"type": "topic", "id": topic_table_id},
            "source": source,
        }
        self._write_snapshot(directory, manifest, rows, rows)
        ref = self._reference_payload("topic", topic_table_id, directory, manifest)
        self._update_index(tenant_id, user_id, "topic", topic_table_id, ref)
        return ref

    def record_saved_report_snapshot(
        self,
        *,
        tenant_id: str,
        user_id: str,
        report_id: str,
        report: dict[str, Any],
        source: str = "legacy_saved_report_migration",
    ) -> dict[str, Any]:
        """Move a pre-Topic_Data saved report into the shared latest snapshot.

        Older reports persisted their returned rows inside SQLite.  Their
        display/edit lifecycle must remain usable after the data-storage
        migration, but the rows must no longer be read from that legacy field.
        A report has one deterministic ``current`` directory, so re-saving a
        report never creates another data version.
        """

        normalized_report_id = _required_text(report_id, "report_id")
        rows = _rows(report.get("rows"))
        directory = self._report_current_dir(tenant_id, normalized_report_id)
        manifest = {
            "schema_version": self.schema_version,
            "created_at": _utc_now(),
            "task_id": str(report.get("analysisTaskId") or ""),
            "execution_id": str(report.get("analysisTaskId") or ""),
            "question": str(report.get("query") or report.get("title") or "历史报告"),
            "status": "completed",
            "analysis_plan": str(report.get("plan") or ""),
            "summary": str(report.get("summary") or ""),
            "sql": "",
            "python_script": "",
            "evidence_id": "",
            "row_count": len(rows),
            "columns": _columns(rows),
            "data_sha256": _rows_hash(rows),
            "report_id": normalized_report_id,
            "version_id": "current",
            "source_reference": {"type": "report", "id": normalized_report_id},
            "source": str(source or "legacy_saved_report_migration")[:200],
        }
        self._write_snapshot(directory, manifest, rows, rows)
        reference = self._reference_payload("report", normalized_report_id, directory, manifest)
        self._update_index(tenant_id, user_id, "report", normalized_report_id, reference)
        return reference

    def latest_topic_table_snapshot(self, tenant_id: str, topic_table_id: str) -> dict[str, Any] | None:
        directory = self._topic_current_dir(tenant_id, topic_table_id)
        manifest = self._read_manifest(directory)
        return self._reference_payload("topic", topic_table_id, directory, manifest) if manifest else None

    def topic_table_snapshots(self, tenant_id: str, topic_ids: list[str]) -> dict[str, dict[str, Any]]:
        return {
            topic_id: snapshot
            for topic_id in topic_ids
            if (snapshot := self.latest_topic_table_snapshot(tenant_id, topic_id)) is not None
        }

    def read_reference(
        self,
        *,
        tenant_id: str,
        user_id: str,
        reference_type: str,
        reference_id: str,
        data_type: str = "data",
    ) -> dict[str, Any]:
        reference_type = str(reference_type or "").strip()
        reference_id = _required_text(reference_id, "topic_data_reference_id")
        if reference_type == "history":
            directory = self._history_dir(tenant_id, user_id, reference_id)
        elif reference_type == "shortcut":
            directory = self._shortcut_dir(tenant_id, user_id, reference_id)
        elif reference_type == "topic":
            latest = self.latest_topic_table_snapshot(tenant_id, reference_id)
            if latest is None:
                raise KeyError("topic_data_not_found")
            directory = self.root / str(latest["folder"])
        elif reference_type == "report":
            directory = self._report_current_dir(tenant_id, reference_id)
        else:
            raise ValueError("topic_data_reference_type_invalid")
        manifest = self._read_manifest(directory)
        if manifest is None:
            raise KeyError("topic_data_not_found")
        file_name = "raw_data.csv" if data_type == "raw" else "data.csv"
        rows = self._read_csv(directory / file_name)
        return {
            "reference_type": reference_type,
            "reference_id": reference_id,
            "data_type": "raw" if data_type == "raw" else "data",
            "folder": directory.relative_to(self.root).as_posix(),
            "manifest": manifest,
            "columns": list(rows[0]) if rows else list(manifest.get("columns") or []),
            "rows": rows[: self.max_inline_rows],
            "row_count": int(manifest.get("row_count") or len(rows)),
            "truncated": len(rows) > self.max_inline_rows,
        }

    def _analysis_manifest(self, task: dict[str, Any], result: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
        intelligent = result.get("intelligent_analysis") if isinstance(result.get("intelligent_analysis"), dict) else {}
        evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
        return {
            "schema_version": self.schema_version,
            "created_at": _utc_now(),
            "task_id": str(task.get("task_id") or ""),
            "execution_id": str(task.get("execution_id") or task.get("task_id") or ""),
            "question": str(task.get("question") or ""),
            "status": str(task.get("status") or ""),
            "analysis_plan": task.get("analysis_plan") if isinstance(task.get("analysis_plan"), dict) else {},
            "summary": str(intelligent.get("analysis_summary") or "") or "\n".join(str(item) for item in task.get("conclusions", []) if item),
            "sql": str(result.get("sql") or ""),
            "python_script": str(result.get("python_script") or ""),
            "evidence_id": str(evidence.get("evidence_id") or ""),
            "row_count": len(rows),
            "columns": _columns(rows),
            "data_sha256": _rows_hash(rows),
        }

    def _write_snapshot(
        self,
        directory: Path,
        manifest: dict[str, Any],
        data_rows: list[dict[str, Any]],
        raw_rows: list[dict[str, Any]],
    ) -> None:
        self._ensure_within_root(directory)
        directory.mkdir(parents=True, exist_ok=True)
        bounded_data = data_rows[: self.max_rows_per_snapshot]
        bounded_raw = raw_rows[: self.max_rows_per_snapshot]
        self._write_csv(directory / "data.csv", bounded_data)
        self._write_csv(directory / "raw_data.csv", bounded_raw)
        self._atomic_write(directory / "query.sql", str(manifest.get("sql") or "") + "\n")
        self._atomic_write(directory / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    def _history_dir(self, tenant_id: str, user_id: str, task_id: str) -> Path:
        return self.root / "analysis" / _segment(tenant_id) / _segment(user_id) / "history" / _segment(task_id)

    def _shortcut_dir(self, tenant_id: str, user_id: str, shortcut_id: str) -> Path:
        return self.root / "analysis" / _segment(tenant_id) / _segment(user_id) / "shortcuts" / _segment(shortcut_id)

    def _topic_current_dir(self, tenant_id: str, topic_table_id: str) -> Path:
        return self.root / _tenant_folder(tenant_id) / "topics" / _segment(topic_table_id) / "current"

    def _report_current_dir(self, tenant_id: str, report_id: str) -> Path:
        return self.root / "reports" / _segment(tenant_id) / _segment(report_id) / "current"

    def _update_index(self, tenant_id: str, user_id: str, reference_type: str, reference_id: str, reference: dict[str, Any]) -> None:
        index_path = self.root / _tenant_folder(tenant_id) / "index.json"
        with self._index_lock:
            try:
                index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else {}
            except (OSError, json.JSONDecodeError):
                index = {}
            entries = index.setdefault("entries", {})
            key = ":".join((_segment(tenant_id), _segment(user_id), reference_type, _segment(reference_id)))
            entries[key] = {**reference, "updated_at": _utc_now()}
            self._atomic_write(index_path, json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    def _reference_payload(self, reference_type: str, reference_id: str, directory: Path, manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            "reference_type": reference_type,
            "reference_id": reference_id,
            "folder": directory.relative_to(self.root).as_posix(),
            "version_id": str(manifest.get("version_id") or ""),
            "task_id": str(manifest.get("task_id") or ""),
            "updated_at": str(manifest.get("created_at") or ""),
            "row_count": int(manifest.get("row_count") or 0),
            "has_data": (directory / "data.csv").is_file(),
            "version_count": 1,
        }

    def _read_manifest(self, directory: Path) -> dict[str, Any] | None:
        self._ensure_within_root(directory)
        path = directory / "manifest.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _read_csv(self, path: Path) -> list[dict[str, str]]:
        self._ensure_within_root(path)
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                return [dict(row) for row in csv.DictReader(handle)]
        except OSError:
            return []

    def _write_csv(self, path: Path, rows: list[dict[str, Any]]) -> None:
        columns = _columns(rows)
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
        if columns:
            writer.writeheader()
            for row in rows:
                writer.writerow({column: _csv_value(row.get(column)) for column in columns})
        self._atomic_write(path, buffer.getvalue())

    def _atomic_write(self, path: Path, content: str) -> None:
        self._ensure_within_root(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    def _ensure_within_root(self, path: Path) -> None:
        try:
            path.resolve().relative_to(self.root)
        except ValueError as exc:
            raise PermissionError("topic_data_path_outside_root") from exc


def _first_result(task: dict[str, Any]) -> dict[str, Any]:
    results = task.get("skill_results") if isinstance(task.get("skill_results"), list) else []
    return dict(results[0]) if results and isinstance(results[0], dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _columns(rows: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for row in rows:
        for key in row:
            label = str(key)
            if label not in result:
                result.append(label)
    return result


def _rows_hash(rows: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _segment(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._")
    return normalized[:120] or "unknown"


def _tenant_folder(tenant_id: str) -> str:
    name = str(tenant_id or "").strip().split(":", 1)[-1].strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name or "\x00" in name:
        raise ValueError("topic_data_tenant_directory_invalid")
    return name


def _required_text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field}_required")
    return normalized


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
