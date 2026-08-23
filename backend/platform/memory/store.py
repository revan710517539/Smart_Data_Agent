from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.platform.storage import connect_sqlite

from .models import MemoryRecord
from .fusion import FUSIBLE_MEMORY_TYPES, fuse_record_content, memory_identity
from .policies import should_persist_memory


MEMORY_TYPES = {"analysis_case", "behavior_habit", "business_fact", "preference", "warning", "other"}
MEMORY_TYPE_ALIASES = {
    "business_rule": "business_fact",
    "metric_correction": "business_fact",
    "user_preference": "preference",
}


class SQLiteMemoryStore:
    """Evidence-backed memory lifecycle; candidate content is never recalled as truth."""

    def __init__(self, db_path: str | Path, initialize: bool = True) -> None:
        self.db_path = str(db_path)
        self._conn = connect_sqlite(self.db_path)
        self._conn.row_factory = sqlite3.Row
        if initialize:
            self.init_schema()
        self._migrate_legacy_rows()

    def close(self) -> None:
        self._conn.close()

    def init_schema(self) -> None:
        if self._table_exists("platform_memory_evidence"):
            return
        if not self._table_exists("platform_memory_records"):
            self._conn.executescript(
                """
                CREATE TABLE platform_memory_records (
                    memory_id TEXT PRIMARY KEY,
                    memory_type TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '{}',
                    source_trace_id TEXT,
                    confidence REAL NOT NULL DEFAULT 0,
                    verified_status TEXT NOT NULL DEFAULT 'draft',
                    created_by TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
        migration = Path(__file__).resolve().parents[1] / "database" / "sql" / "0008_memory_lifecycle.sql"
        self._conn.executescript(migration.read_text(encoding="utf-8"))
        self._conn.commit()

    def write(self, record: MemoryRecord, force: bool = False) -> bool:
        if not force and not should_persist_memory(record):
            return False
        existing_memory_id = self._conn.execute(
            "SELECT 1 FROM platform_memory_records WHERE tenant_id = ? AND memory_id = ?",
            (record.tenant_id, record.memory_id),
        ).fetchone()
        if existing_memory_id:
            return False
        memory_type = canonical_memory_type(record.memory_type)
        status = _canonical_status(record.verified_status)
        if status == "active" and not force:
            status = "candidate"
        subject_type = record.subject_type if record.subject_type in {"user", "role", "org", "tenant"} else "tenant"
        subject_id = str(record.subject_id or (record.created_by if subject_type == "user" else record.tenant_id) or record.tenant_id)
        superseded_rows: list[sqlite3.Row] = []
        content = dict(record.content)
        if memory_type in FUSIBLE_MEMORY_TYPES:
            identity = memory_identity(memory_type, content, title=record.title or record.subject)
            candidates = self._conn.execute(
                """
                SELECT memory_id, title, content, status, updated_at
                FROM platform_memory_records
                WHERE tenant_id = ? AND memory_type = ? AND subject_type = ?
                  AND subject_id = ? AND status IN ('candidate','review','active')
                ORDER BY updated_at, memory_id
                LIMIT 500
                """,
                (record.tenant_id, memory_type, subject_type, subject_id),
            ).fetchall()
            superseded_rows = [
                row
                for row in candidates
                if memory_identity(memory_type, _load_json(row["content"], {}), title=str(row["title"])).merge_key
                == identity.merge_key
            ]
            content = fuse_record_content(
                memory_type,
                record.title or record.subject,
                [*(_load_json(row["content"], {}) for row in superseded_rows), content],
                memory_ids=(str(row["memory_id"]) for row in superseded_rows),
            )
        content_json = _json(content)
        content_hash = hashlib.sha256(content_json.encode("utf-8")).hexdigest()
        existing = self._conn.execute(
            """
            SELECT memory_id FROM platform_memory_records
            WHERE tenant_id = ? AND memory_type = ? AND subject_type = ?
              AND subject_id = ? AND content_hash = ?
              AND status IN ('candidate','review','active')
            """,
            (record.tenant_id, memory_type, subject_type, subject_id, content_hash),
        ).fetchone()
        if existing:
            return False
        now = record.created_at or _utcnow()
        valid_from = now
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_memory_records(
                    tenant_id, memory_id, memory_type, subject_type, subject_id,
                    title, content, content_hash, status, confidence, weight,
                    valid_from, expires_at, supersedes_memory_id, source_trace_id,
                    created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.tenant_id,
                    record.memory_id,
                    memory_type,
                    subject_type,
                    subject_id,
                    record.title or record.subject[:500] or memory_type,
                    content_json,
                    content_hash,
                    status,
                    max(0, min(float(record.confidence), 1)),
                    max(0, float(record.weight)),
                    valid_from,
                    record.expires_at,
                    record.supersedes_memory_id or (str(superseded_rows[-1]["memory_id"]) if superseded_rows else None),
                    record.source_trace_id,
                    record.created_by,
                    now,
                    now,
                ),
            )
            for previous in superseded_rows:
                previous_status = str(previous["status"])
                if previous_status in {"candidate", "review"} or status == "active":
                    self._conn.execute(
                        """
                        UPDATE platform_memory_records
                        SET status = 'superseded', updated_at = ?
                        WHERE tenant_id = ? AND memory_id = ?
                          AND status IN ('candidate','review','active')
                        """,
                        (now, record.tenant_id, str(previous["memory_id"])),
                    )
            if record.evidence_type and record.evidence_id and record.evidence_hash:
                if len(record.evidence_hash) != 64:
                    raise ValueError("memory_evidence_hash_must_be_sha256")
                self._conn.execute(
                    """
                    INSERT INTO platform_memory_evidence(
                        tenant_id, memory_evidence_id, memory_id, evidence_type,
                        evidence_id, evidence_hash, support_type, created_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'supports', ?, ?)
                    """,
                    (
                        record.tenant_id,
                        f"me_{uuid4().hex}",
                        record.memory_id,
                        record.evidence_type,
                        record.evidence_id,
                        record.evidence_hash,
                        record.created_by,
                        now,
                    ),
                )
        return True

    def search(
        self,
        tenant_id: str,
        memory_type: str | None = None,
        subject: str | None = None,
        *,
        statuses: tuple[str, ...] | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        clauses = ["tenant_id = ?"]
        params: list[Any] = [tenant_id]
        if memory_type:
            clauses.append("memory_type = ?")
            params.append(canonical_memory_type(memory_type))
        if subject:
            clauses.append("lower(title) LIKE ?")
            params.append(f"%{subject.lower()}%")
        if subject_type:
            clauses.append("subject_type = ?")
            params.append(subject_type)
        if subject_id:
            clauses.append("subject_id = ?")
            params.append(subject_id)
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            params.extend(statuses)
        clauses.append("(expires_at IS NULL OR expires_at > ?)")
        params.append(_utcnow())
        params.append(max(1, min(int(limit), 500)))
        rows = self._conn.execute(
            f"""
            SELECT * FROM platform_memory_records
            WHERE {' AND '.join(clauses)}
            ORDER BY confidence * weight DESC, valid_from DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        return [_memory_record(row) for row in rows]

    def review(
        self,
        tenant_id: str,
        memory_id: str,
        decision: str,
        reviewer_user_id: str,
        *,
        comments: str = "",
    ) -> dict[str, Any]:
        normalized = str(decision or "").strip().lower()
        if normalized not in {"approve", "reject", "request_change", "supersede", "expire"}:
            raise ValueError("invalid_memory_review_decision")
        row = self._conn.execute(
            "SELECT * FROM platform_memory_records WHERE tenant_id = ? AND memory_id = ?",
            (tenant_id, memory_id),
        ).fetchone()
        if not row:
            raise KeyError("memory_record_not_found")
        if str(row["status"]) not in {"candidate", "review", "active"}:
            raise ValueError("memory_record_cannot_be_reviewed")
        if normalized == "approve" and str(row["created_by"] or "") == reviewer_user_id:
            raise PermissionError("four_eyes_memory_review_required")
        evidence_count = int(
            self._conn.execute(
                "SELECT COUNT(*) FROM platform_memory_evidence WHERE tenant_id = ? AND memory_id = ? AND support_type = 'supports'",
                (tenant_id, memory_id),
            ).fetchone()[0]
        )
        if normalized == "approve" and str(row["memory_type"]) in {"analysis_case", "business_fact", "warning"} and evidence_count == 0:
            raise ValueError("memory_evidence_required_for_approval")
        next_status = {
            "approve": "active",
            "reject": "rejected",
            "request_change": "review",
            "supersede": "superseded",
            "expire": "expired",
        }[normalized]
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                "UPDATE platform_memory_records SET status = ?, updated_at = ? WHERE tenant_id = ? AND memory_id = ?",
                (next_status, now, tenant_id, memory_id),
            )
            if normalized == "approve" and row["supersedes_memory_id"]:
                self._conn.execute(
                    "UPDATE platform_memory_records SET status = 'superseded', updated_at = ? WHERE tenant_id = ? AND memory_id = ?",
                    (now, tenant_id, row["supersedes_memory_id"]),
                )
            self._conn.execute(
                """
                INSERT INTO platform_memory_reviews(
                    tenant_id, memory_review_id, memory_id, reviewer_user_id,
                    review_type, decision, comments, review_evidence,
                    reviewed_at, created_at
                ) VALUES (?, ?, ?, ?, 'human', ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    f"mr_{uuid4().hex}",
                    memory_id,
                    reviewer_user_id,
                    normalized,
                    str(comments or "")[:2000],
                    _json({"supporting_evidence_count": evidence_count}),
                    now,
                    now,
                ),
            )
        return self.get(tenant_id, memory_id)

    def get(self, tenant_id: str, memory_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM platform_memory_records WHERE tenant_id = ? AND memory_id = ?",
            (tenant_id, memory_id),
        ).fetchone()
        if not row:
            raise KeyError("memory_record_not_found")
        result = dict(row)
        result["content"] = _load_json(result["content"], {})
        result["evidence_count"] = int(
            self._conn.execute(
                "SELECT COUNT(*) FROM platform_memory_evidence WHERE tenant_id = ? AND memory_id = ?",
                (tenant_id, memory_id),
            ).fetchone()[0]
        )
        return result

    def list_candidates(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT memory_id FROM platform_memory_records
            WHERE tenant_id = ? AND status IN ('candidate','review')
            ORDER BY created_at DESC
            """,
            (tenant_id,),
        ).fetchall()
        return [self.get(tenant_id, str(row["memory_id"])) for row in rows]

    def _migrate_legacy_rows(self) -> None:
        if not self._table_exists("platform_memory_records_legacy"):
            return
        rows = self._conn.execute("SELECT * FROM platform_memory_records_legacy").fetchall()
        for row in rows:
            try:
                self.write(
                    MemoryRecord(
                        memory_id=str(row["memory_id"]),
                        memory_type=str(row["memory_type"]),
                        tenant_id=str(row["tenant_id"]),
                        subject=str(row["subject"]),
                        content=_load_json(row["content"], {}),
                        source_trace_id=row["source_trace_id"],
                        confidence=float(row["confidence"] or 0),
                        verified_status=str(row["verified_status"] or "candidate"),
                        subject_type="tenant",
                        subject_id=str(row["tenant_id"]),
                        created_by=row["created_by"],
                        created_at=str(row["created_at"]),
                    ),
                    force=True,
                )
            except (sqlite3.IntegrityError, ValueError):
                continue

    def _table_exists(self, table_name: str) -> bool:
        return bool(
            self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone()
        )


class InMemoryMemoryStore(SQLiteMemoryStore):
    def __init__(self) -> None:
        self.db_path = ":memory:"
        self._conn = connect_sqlite(":memory:")
        self._conn.row_factory = sqlite3.Row
        self.init_schema()


def canonical_memory_type(value: str) -> str:
    normalized = str(value or "other").strip().lower()
    normalized = MEMORY_TYPE_ALIASES.get(normalized, normalized)
    return normalized if normalized in MEMORY_TYPES else "other"


def _canonical_status(value: str) -> str:
    normalized = str(value or "candidate").strip().lower()
    return {
        "draft": "candidate",
        "verified": "active",
        "approved": "active",
    }.get(normalized, normalized if normalized in {"candidate", "review", "active", "superseded", "expired", "rejected"} else "candidate")


def _memory_record(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        memory_id=str(row["memory_id"]),
        memory_type=str(row["memory_type"]),
        tenant_id=str(row["tenant_id"]),
        subject=str(row["title"]),
        content=_load_json(row["content"], {}),
        source_trace_id=row["source_trace_id"],
        confidence=float(row["confidence"] or 0),
        verified_status=str(row["status"]),
        subject_type=str(row["subject_type"]),
        subject_id=str(row["subject_id"]),
        title=str(row["title"]),
        weight=float(row["weight"] or 0),
        expires_at=row["expires_at"],
        supersedes_memory_id=row["supersedes_memory_id"],
        created_by=row["created_by"],
        created_at=str(row["created_at"]),
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return default


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
