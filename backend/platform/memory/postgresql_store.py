from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.postgresql import PostgreSQLConnectionPool

from .models import MemoryRecord
from .policies import should_persist_memory
from .store import _canonical_status, canonical_memory_type


class PostgreSQLMemoryStore:
    """Evidence-backed production memory lifecycle with four-eyes activation."""

    def __init__(self, pool: PostgreSQLConnectionPool, *, owns_pool: bool = False) -> None:
        self.pool = pool
        self.owns_pool = owns_pool

    def close(self) -> None:
        if self.owns_pool:
            self.pool.close()

    def write(self, record: MemoryRecord, force: bool = False) -> bool:
        if not force and not should_persist_memory(record):
            return False
        memory_type = canonical_memory_type(record.memory_type)
        status = _canonical_status(record.verified_status)
        if status == "active" and not force:
            status = "candidate"
        subject_type = record.subject_type if record.subject_type in {"user", "role", "org", "tenant"} else "tenant"
        subject_id = str(
            record.subject_id
            or (record.created_by if subject_type == "user" else record.tenant_id)
            or record.tenant_id
        )
        content_json = _json(record.content)
        content_hash = hashlib.sha256(content_json.encode("utf-8")).hexdigest()
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, record.tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, record.created_by, required=False) if record.created_by else None
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1 FROM platform_memory_records
                    WHERE tenant_id = %s AND memory_type = %s AND subject_type = %s
                      AND subject_id = %s AND content_hash = %s
                      AND status IN ('candidate','review','active')
                    """,
                    (tenant_key, memory_type, subject_type, subject_id, content_hash),
                )
                if cursor.fetchone():
                    return False
                supersedes_id = None
                if record.supersedes_memory_id:
                    cursor.execute(
                        "SELECT memory_id FROM platform_memory_records WHERE tenant_id = %s AND memory_key = %s",
                        (tenant_key, record.supersedes_memory_id),
                    )
                    row = cursor.fetchone()
                    supersedes_id = _value(row, "memory_id", 0) if row else None
                cursor.execute(
                    """
                    INSERT INTO platform_memory_records(
                        tenant_id, memory_key, memory_type, subject_type, subject_id,
                        title, content, content_hash, status, confidence, weight,
                        valid_from, expires_at, supersedes_memory_id, source_trace_id,
                        created_by, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s,
                        %s::timestamptz, %s::timestamptz, %s, %s, %s,
                        %s::timestamptz, %s::timestamptz
                    ) RETURNING memory_id
                    """,
                    (
                        tenant_key, record.memory_id, memory_type, subject_type, subject_id,
                        record.title or record.subject[:500] or memory_type, content_json,
                        content_hash, status, max(0, min(float(record.confidence), 1)),
                        max(0, float(record.weight)), record.created_at, record.expires_at,
                        supersedes_id, record.source_trace_id, actor_key,
                        record.created_at, record.created_at,
                    ),
                )
                memory_id = _value(cursor.fetchone(), "memory_id", 0)
                if record.evidence_type and record.evidence_id and record.evidence_hash:
                    if len(record.evidence_hash) != 64:
                        raise ValueError("memory_evidence_hash_must_be_sha256")
                    cursor.execute(
                        """
                        INSERT INTO platform_memory_evidence(
                            tenant_id, memory_id, evidence_type, evidence_id,
                            evidence_hash, support_type, created_by
                        ) VALUES (%s, %s, %s, %s, %s, 'supports', %s)
                        ON CONFLICT (memory_id, evidence_type, evidence_id) DO NOTHING
                        """,
                        (
                            tenant_key, memory_id, record.evidence_type,
                            record.evidence_id, record.evidence_hash, actor_key,
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
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            clauses = ["m.tenant_id = %s", "(m.expires_at IS NULL OR m.expires_at > now())"]
            params: list[Any] = [tenant_key]
            if memory_type:
                clauses.append("m.memory_type = %s")
                params.append(canonical_memory_type(memory_type))
            if subject:
                clauses.append("m.title ILIKE %s")
                params.append(f"%{subject}%")
            if subject_type:
                clauses.append("m.subject_type = %s")
                params.append(subject_type)
            if subject_id:
                clauses.append("m.subject_id = %s")
                params.append(subject_id)
            if statuses:
                clauses.append("m.status = ANY(%s)")
                params.append(list(statuses))
            params.append(max(1, min(int(limit), 500)))
            with connection.cursor() as cursor:
                cursor.execute(
                    self._select_sql(" AND ".join(clauses))
                    + " ORDER BY m.confidence * m.weight DESC, m.valid_from DESC LIMIT %s",
                    tuple(params),
                )
                rows = cursor.fetchall()
        return [self._record_from_row(row) for row in rows]

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
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            reviewer_key = PostgreSQLIdentityResolver.user_id(connection, reviewer_user_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT m.memory_id, m.memory_type, m.status, m.created_by,
                           m.supersedes_memory_id,
                           (SELECT COUNT(*) FROM platform_memory_evidence e
                            WHERE e.memory_id = m.memory_id AND e.support_type = 'supports') AS evidence_count
                    FROM platform_memory_records m
                    WHERE m.tenant_id = %s AND m.memory_key = %s
                    FOR UPDATE OF m
                    """,
                    (tenant_key, memory_id),
                )
                row = cursor.fetchone()
                if not row:
                    raise KeyError("memory_record_not_found")
                if str(_value(row, "status", 2)) not in {"candidate", "review", "active"}:
                    raise ValueError("memory_record_cannot_be_reviewed")
                if normalized == "approve" and _value(row, "created_by", 3) == reviewer_key:
                    raise PermissionError("four_eyes_memory_review_required")
                evidence_count = int(_value(row, "evidence_count", 5) or 0)
                if normalized == "approve" and str(_value(row, "memory_type", 1)) in {"analysis_case", "business_fact", "warning"} and evidence_count == 0:
                    raise ValueError("memory_evidence_required_for_approval")
                next_status = {
                    "approve": "active", "reject": "rejected", "request_change": "review",
                    "supersede": "superseded", "expire": "expired",
                }[normalized]
                cursor.execute(
                    """
                    UPDATE platform_memory_records
                    SET status = %s, updated_at = now(), lock_version = lock_version + 1
                    WHERE memory_id = %s
                    """,
                    (next_status, _value(row, "memory_id", 0)),
                )
                supersedes_id = _value(row, "supersedes_memory_id", 4)
                if normalized == "approve" and supersedes_id:
                    cursor.execute(
                        "UPDATE platform_memory_records SET status = 'superseded', updated_at = now(), lock_version = lock_version + 1 WHERE memory_id = %s",
                        (supersedes_id,),
                    )
                cursor.execute(
                    """
                    INSERT INTO platform_memory_reviews(
                        tenant_id, memory_id, reviewer_user_id, review_type,
                        decision, comments, review_evidence, reviewed_at, created_by
                    ) VALUES (%s, %s, %s, 'human', %s, %s, %s::jsonb, now(), %s)
                    """,
                    (
                        tenant_key, _value(row, "memory_id", 0), reviewer_key, normalized,
                        str(comments or "")[:2000], _json({"supporting_evidence_count": evidence_count}), reviewer_key,
                    ),
                )
        return self.get(tenant_id, memory_id)

    def get(self, tenant_id: str, memory_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._select_sql("m.tenant_id = %s AND m.memory_key = %s"), (tenant_key, memory_id))
                row = cursor.fetchone()
        if not row:
            raise KeyError("memory_record_not_found")
        return self._dict_from_row(row)

    def list_candidates(self, tenant_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    self._select_sql("m.tenant_id = %s AND m.status IN ('candidate','review')")
                    + " ORDER BY m.created_at DESC",
                    (tenant_key,),
                )
                rows = cursor.fetchall()
        return [self._dict_from_row(row) for row in rows]

    @staticmethod
    def _select_sql(where: str) -> str:
        return f"""
            SELECT m.memory_key, m.memory_type, t.tenant_code, m.title, m.content,
                   m.source_trace_id, m.confidence, m.status, m.subject_type,
                   m.subject_id, m.weight, m.expires_at, superseded.memory_key AS supersedes_key,
                   creator.external_subject AS created_by, m.created_at,
                   COUNT(e.memory_evidence_id) AS evidence_count
            FROM platform_memory_records m
            JOIN platform_tenants t ON t.tenant_id = m.tenant_id
            LEFT JOIN platform_memory_records superseded ON superseded.memory_id = m.supersedes_memory_id
            LEFT JOIN platform_user_profiles creator ON creator.user_id = m.created_by
            LEFT JOIN platform_memory_evidence e ON e.memory_id = m.memory_id
            WHERE {where}
            GROUP BY m.memory_id, t.tenant_code, superseded.memory_key, creator.external_subject
        """

    @staticmethod
    def _record_from_row(row: Any) -> MemoryRecord:
        return MemoryRecord(
            memory_id=str(_value(row, "memory_key", 0)),
            memory_type=str(_value(row, "memory_type", 1)),
            tenant_id=str(_value(row, "tenant_code", 2)),
            subject=str(_value(row, "title", 3)),
            content=dict(_json_value(_value(row, "content", 4), {})),
            source_trace_id=_value(row, "source_trace_id", 5),
            confidence=float(_value(row, "confidence", 6) or 0),
            verified_status=str(_value(row, "status", 7)),
            subject_type=str(_value(row, "subject_type", 8)),
            subject_id=str(_value(row, "subject_id", 9)),
            title=str(_value(row, "title", 3)),
            weight=float(_value(row, "weight", 10) or 0),
            expires_at=_iso_optional(_value(row, "expires_at", 11)),
            supersedes_memory_id=_value(row, "supersedes_key", 12),
            created_by=_value(row, "created_by", 13),
            created_at=_iso_optional(_value(row, "created_at", 14)) or "",
        )

    @classmethod
    def _dict_from_row(cls, row: Any) -> dict[str, Any]:
        record = cls._record_from_row(row)
        return {
            "memory_id": record.memory_id,
            "memory_type": record.memory_type,
            "tenant_id": record.tenant_id,
            "subject_type": record.subject_type,
            "subject_id": record.subject_id,
            "title": record.title,
            "content": record.content,
            "source_trace_id": record.source_trace_id,
            "confidence": record.confidence,
            "status": record.verified_status,
            "weight": record.weight,
            "expires_at": record.expires_at,
            "supersedes_memory_id": record.supersedes_memory_id,
            "created_by": record.created_by,
            "created_at": record.created_at,
            "evidence_count": int(_value(row, "evidence_count", 15) or 0),
        }

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self.pool.connection() as connection:
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value) if isinstance(value, str) else value


def _iso_optional(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]
