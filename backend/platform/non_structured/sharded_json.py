from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ShardedJSONStore:
    """Tenant/topic sharded JSONL content with atomic rebuildable indexes."""

    def __init__(self, root: str | Path, *, max_shard_bytes: int = 8 * 1024 * 1024, max_documents: int = 1_000) -> None:
        if max_shard_bytes < 1_024 or max_documents < 1:
            raise ValueError("non_structured_shard_limits_invalid")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_shard_bytes = max_shard_bytes
        self.max_documents = max_documents
        self._lock = threading.RLock()

    def append(self, *, tenant_id: str, content_type: str, topic: str, document_id: str, content: dict[str, Any], tags: list[str] | None = None, permission_scope: dict[str, Any] | None = None, status: str = "active", now: datetime | None = None) -> dict[str, Any]:
        timestamp = now or datetime.now(timezone.utc)
        tenant = _segment(tenant_id)
        kind = _segment(content_type)
        subject = _segment(topic)
        identifier = _segment(document_id)
        directory = self.root / tenant / kind / subject / timestamp.strftime("%Y") / timestamp.strftime("%m")
        self._within_root(directory)
        directory.mkdir(parents=True, exist_ok=True)
        record = {"document_id": identifier, "topic": topic, "tags": _strings(tags), "permission_scope": permission_scope if isinstance(permission_scope, dict) else {}, "status": status, "content": content, "created_at": timestamp.isoformat()}
        encoded = (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        if len(encoded) > self.max_shard_bytes:
            raise ValueError("non_structured_document_too_large")
        with self._lock:
            index = self._read_index(directory)
            if identifier in index["documents"]:
                raise ValueError("non_structured_document_exists")
            shard_no = self._select_shard(directory, index, len(encoded))
            shard = directory / f"shard-{shard_no:04d}.json"
            offset = shard.stat().st_size if shard.exists() else 0
            with shard.open("ab") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            entry = {"topic": topic, "tags": record["tags"], "permission_scope": record["permission_scope"], "status": status, "shard": shard.name, "offset": offset, "length": len(encoded), "content_hash": hashlib.sha256(encoded.rstrip(b"\n")).hexdigest(), "created_at": record["created_at"]}
            index["documents"][identifier] = entry
            stats = index["shards"].setdefault(shard.name, {"documents": 0, "bytes": 0})
            stats["documents"] += 1
            stats["bytes"] += len(encoded)
            index["version"] += 1
            complete_index = self._write_index(directory, index)
            self._update_topic_index(tenant, kind, subject, directory, complete_index)
        return {"document_id": identifier, **entry}

    def get(self, *, tenant_id: str, content_type: str, topic: str, document_id: str, year: str | None = None, month: str | None = None) -> dict[str, Any] | None:
        tenant = _segment(tenant_id)
        kind = _segment(content_type)
        subject = _segment(topic)
        identifier = _segment(document_id)
        directories = self._topic_directories(tenant, kind, subject, year, month)
        for directory in directories:
            index = self._read_index(directory)
            entry = index["documents"].get(identifier)
            if not entry:
                continue
            shard = directory / entry["shard"]
            self._within_root(shard)
            with shard.open("rb") as handle:
                handle.seek(int(entry["offset"]))
                payload = handle.read(int(entry["length"])).rstrip(b"\n")
            if hashlib.sha256(payload).hexdigest() != entry["content_hash"]:
                raise RuntimeError("non_structured_content_hash_mismatch")
            decoded = json.loads(payload.decode("utf-8"))
            if decoded.get("document_id") != identifier:
                raise RuntimeError("non_structured_index_offset_invalid")
            return decoded
        return None

    def rebuild_index(self, directory: str | Path) -> dict[str, Any]:
        target = Path(directory).resolve()
        self._within_root(target)
        index = {"version": 1, "documents": {}, "shards": {}, "checksum": ""}
        with self._lock:
            for shard in sorted(target.glob("shard-*.json")):
                offset = 0
                count = 0
                with shard.open("rb") as handle:
                    for line in handle:
                        payload = line.rstrip(b"\n")
                        record = json.loads(payload.decode("utf-8"))
                        identifier = _segment(record.get("document_id"))
                        if identifier in index["documents"]:
                            raise RuntimeError("non_structured_duplicate_document")
                        index["documents"][identifier] = {"topic": str(record.get("topic") or ""), "tags": _strings(record.get("tags")), "permission_scope": record.get("permission_scope") if isinstance(record.get("permission_scope"), dict) else {}, "status": str(record.get("status") or "active"), "shard": shard.name, "offset": offset, "length": len(line), "content_hash": hashlib.sha256(payload).hexdigest(), "created_at": str(record.get("created_at") or "")}
                        offset += len(line)
                        count += 1
                index["shards"][shard.name] = {"documents": count, "bytes": offset}
            complete_index = self._write_index(target, index)
            relative = target.relative_to(self.root).parts
            if len(relative) != 5:
                raise ValueError("non_structured_rebuild_directory_invalid")
            tenant, kind, subject, _, _ = relative
            self._update_topic_index(tenant, kind, subject, target, complete_index)
        return complete_index

    def _select_shard(self, directory: Path, index: dict[str, Any], incoming_bytes: int) -> int:
        for shard_no in range(1, 100_000):
            name = f"shard-{shard_no:04d}.json"
            stats = index["shards"].get(name, {"documents": 0, "bytes": 0})
            if stats["documents"] < self.max_documents and stats["bytes"] + incoming_bytes <= self.max_shard_bytes:
                return shard_no
        raise RuntimeError("non_structured_shard_capacity_exhausted")

    def _read_index(self, directory: Path) -> dict[str, Any]:
        path = directory / "index.json"
        if not path.exists():
            return {"version": 0, "documents": {}, "shards": {}, "checksum": ""}
        payload = json.loads(path.read_text(encoding="utf-8"))
        checksum = str(payload.pop("checksum", ""))
        if checksum != _checksum(payload):
            raise RuntimeError("non_structured_index_checksum_mismatch")
        return {**payload, "checksum": checksum}

    def _write_index(self, directory: Path, index: dict[str, Any]) -> dict[str, Any]:
        payload = {key: value for key, value in index.items() if key != "checksum"}
        complete = {**payload, "checksum": _checksum(payload)}
        target = directory / "index.json"
        temporary = target.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(complete, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        return complete

    def _update_topic_index(self, tenant: str, kind: str, subject: str, directory: Path, index: dict[str, Any]) -> None:
        root = self.root / tenant / "topic-index"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{kind}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 0, "topics": {}}
        except json.JSONDecodeError:
            payload = {"version": 0, "topics": {}}
        relative = directory.relative_to(self.root).as_posix()
        payload["version"] = int(payload.get("version") or 0) + 1
        payload.setdefault("topics", {}).setdefault(subject, {})[relative] = {"documents": len(index["documents"]), "index_checksum": index.get("checksum", "")}
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def _topic_directories(self, tenant: str, kind: str, subject: str, year: str | None, month: str | None) -> list[Path]:
        base = self.root / tenant / kind / subject
        self._within_root(base)
        if year and month:
            candidates = [base / _segment(year) / _segment(month)]
        elif year:
            candidates = sorted((base / _segment(year)).glob("[0-1][0-9]"), reverse=True)
        else:
            candidates = sorted(base.glob("[0-9][0-9][0-9][0-9]/[0-1][0-9]"), reverse=True)
        return [item for item in candidates if item.is_dir()]

    def _within_root(self, path: Path) -> None:
        resolved = path.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise PermissionError("non_structured_path_outside_root")


def _segment(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text in {".", ".."} or "/" in text or "\\" in text or len(text) > 160:
        raise ValueError("non_structured_segment_invalid")
    return text.replace(":", "_")


def _strings(value: Any) -> list[str]:
    return [str(item).strip()[:120] for item in value[:100] if str(item or "").strip()] if isinstance(value, list) else []


def _checksum(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
