from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.platform.storage import connect_sqlite

from .models import KnowledgeDocument, KnowledgeHit


GLOBAL_KNOWLEDGE_TENANT = "__global__"
DOCUMENT_TYPES = {"metric_rule", "business_rule", "report", "case", "manual", "policy", "market", "other"}
CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}


class SQLiteKnowledgeStore:
    """Versioned, tenant-scoped knowledge store with chunk-level retrieval."""

    def __init__(self, db_path: str | Path, documents: list[KnowledgeDocument] | None = None, initialize: bool = True) -> None:
        self.db_path = str(db_path)
        self._conn = connect_sqlite(self.db_path)
        self._conn.row_factory = sqlite3.Row
        if initialize:
            self.init_schema()
        self._migrate_legacy_rows()
        for document in documents or []:
            self.add(document)

    def close(self) -> None:
        self._conn.close()

    def init_schema(self) -> None:
        if self._table_exists("platform_knowledge_versions"):
            return
        if not self._table_exists("platform_knowledge_documents"):
            self._conn.executescript(
                """
                CREATE TABLE platform_knowledge_documents (
                    doc_id TEXT PRIMARY KEY,
                    tenant_id TEXT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'document',
                    domains TEXT NOT NULL DEFAULT '[]',
                    tags TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
        if not self._table_exists("platform_data_artifacts"):
            self._conn.executescript(
                """
                CREATE TABLE platform_data_artifacts (
                    tenant_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, artifact_id)
                );
                """
            )
        migration = Path(__file__).resolve().parents[1] / "database" / "sql" / "0007_knowledge_lifecycle.sql"
        self._conn.executescript(migration.read_text(encoding="utf-8"))
        processing_migration = Path(__file__).resolve().parents[1] / "database" / "sql" / "0019_attachment_processing_error.sql"
        self._conn.executescript(processing_migration.read_text(encoding="utf-8"))
        self._conn.commit()

    def add(self, document: KnowledgeDocument) -> None:
        """Seed or import an already-curated document as active knowledge."""

        tenant_id = document.tenant_id or GLOBAL_KNOWLEDGE_TENANT
        existing = self._conn.execute(
            "SELECT document_id, current_version_no FROM platform_knowledge_documents WHERE tenant_id = ? AND document_id = ?",
            (tenant_id, document.doc_id),
        ).fetchone()
        content_hash = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
        if existing:
            current_hash = self._conn.execute(
                """
                SELECT content_hash FROM platform_knowledge_versions
                WHERE tenant_id = ? AND document_id = ? AND version_no = ?
                """,
                (tenant_id, document.doc_id, int(existing["current_version_no"] or 0)),
            ).fetchone()
            if current_hash and str(current_hash["content_hash"]) == content_hash:
                return
            version_no = int(existing["current_version_no"] or 0) + 1
        else:
            version_no = 1
        self._write_document_version(
            tenant_id=tenant_id,
            document_id=document.doc_id,
            document_code=document.doc_id,
            title=document.title,
            document_type=_document_type(document.source_type),
            owner_user_id=document.owner_user_id or "system",
            classification="internal",
            domains=document.domains,
            tags=document.tags,
            content=document.content,
            language="zh-CN",
            parser_name="seed_import",
            created_by=document.owner_user_id or "system",
            version_no=version_no,
            status="active",
            published=True,
        )

    def create_document(
        self,
        tenant_id: str,
        payload: dict[str, Any],
        created_by: str,
        *,
        content: str | None = None,
        source_attachment_id: str | None = None,
        content_artifact_id: str | None = None,
        parser_name: str = "plain_text",
    ) -> dict[str, Any]:
        title = _required_text(payload.get("title"), "title", 500)
        text = _required_text(content if content is not None else payload.get("content"), "content", 2_000_000)
        document_id = str(payload.get("document_id") or payload.get("doc_id") or f"kd_{uuid4().hex}")
        document_code = str(payload.get("document_code") or document_id).strip()
        if not document_code or len(document_code) > 200:
            raise ValueError("invalid_document_code")
        document_type = _document_type(payload.get("document_type", payload.get("source_type", "other")))
        classification = str(payload.get("classification") or "internal").strip()
        if classification not in CLASSIFICATIONS:
            raise ValueError("invalid_knowledge_classification")
        domains = _string_tuple(payload.get("domains", ()))
        tags = _string_tuple(payload.get("tags", ()))
        self._write_document_version(
            tenant_id=tenant_id,
            document_id=document_id,
            document_code=document_code,
            title=title,
            document_type=document_type,
            owner_user_id=created_by,
            classification=classification,
            domains=domains,
            tags=tags,
            content=text,
            language=str(payload.get("language") or "zh-CN")[:32],
            parser_name=parser_name,
            created_by=created_by,
            version_no=1,
            status="review",
            published=False,
            source_attachment_id=source_attachment_id,
            content_artifact_id=content_artifact_id,
        )
        return self.get_document(tenant_id, document_id)

    def create_version(
        self,
        tenant_id: str,
        document_id: str,
        content: str,
        created_by: str,
        *,
        source_attachment_id: str | None = None,
        content_artifact_id: str | None = None,
        parser_name: str = "plain_text",
    ) -> dict[str, Any]:
        document = self.get_document(tenant_id, document_id)
        if document["owner_user_id"] != created_by:
            raise PermissionError("knowledge_document_owner_required")
        version_no = int(
            self._conn.execute(
                "SELECT COALESCE(MAX(version_no), 0) FROM platform_knowledge_versions WHERE tenant_id = ? AND document_id = ?",
                (tenant_id, document_id),
            ).fetchone()[0]
        ) + 1
        self._write_document_version(
            tenant_id=tenant_id,
            document_id=document_id,
            document_code=document["document_code"],
            title=document["title"],
            document_type=document["document_type"],
            owner_user_id=document["owner_user_id"],
            classification=document["classification"],
            domains=tuple(document["domains"]),
            tags=tuple(document["tags"]),
            content=_required_text(content, "content", 2_000_000),
            language="zh-CN",
            parser_name=parser_name,
            created_by=created_by,
            version_no=version_no,
            status="review",
            published=False,
            source_attachment_id=source_attachment_id,
            content_artifact_id=content_artifact_id,
        )
        return self.get_document(tenant_id, document_id)

    def review_document(self, tenant_id: str, document_id: str, decision: str, reviewer: str) -> dict[str, Any]:
        normalized = str(decision or "").strip().lower()
        if normalized not in {"approve", "reject", "archive"}:
            raise ValueError("invalid_knowledge_review_decision")
        document = self.get_document(tenant_id, document_id)
        if normalized != "archive" and document["status"] != "review":
            raise ValueError("knowledge_document_is_not_in_review")
        version = self._conn.execute(
            """
            SELECT * FROM platform_knowledge_versions
            WHERE tenant_id = ? AND document_id = ? AND version_no = ?
            """,
            (tenant_id, document_id, document["current_version_no"]),
        ).fetchone()
        if not version:
            raise KeyError("knowledge_version_not_found")
        if normalized == "approve" and str(version["created_by"]) == reviewer:
            raise PermissionError("four_eyes_knowledge_review_required")
        now = _utcnow()
        status = {"approve": "active", "reject": "failed", "archive": "archived"}[normalized]
        with self._conn:
            self._conn.execute(
                "UPDATE platform_knowledge_documents SET status = ?, updated_at = ? WHERE tenant_id = ? AND document_id = ?",
                (status, now, tenant_id, document_id),
            )
            if normalized == "approve":
                self._conn.execute(
                    """
                    UPDATE platform_knowledge_versions
                    SET published_at = ?, reviewed_by = ?
                    WHERE tenant_id = ? AND knowledge_version_id = ?
                    """,
                    (now, reviewer, tenant_id, version["knowledge_version_id"]),
                )
        return self.get_document(tenant_id, document_id)

    def get_document(self, tenant_id: str, document_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM platform_knowledge_documents WHERE tenant_id = ? AND document_id = ?",
            (tenant_id, document_id),
        ).fetchone()
        if not row:
            raise KeyError("knowledge_document_not_found")
        return _document_row(row)

    def list_documents(self, tenant_id: str, include_archived: bool = False) -> list[dict[str, Any]]:
        clauses = ["tenant_id = ?"]
        params: list[Any] = [tenant_id]
        if not include_archived:
            clauses.append("status <> 'archived'")
        rows = self._conn.execute(
            f"SELECT * FROM platform_knowledge_documents WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC",
            tuple(params),
        ).fetchall()
        return [_document_row(row) for row in rows]

    def search(
        self,
        query: str,
        tenant_id: str | None = None,
        domains: tuple[str, ...] = (),
        limit: int = 5,
    ) -> list[KnowledgeHit]:
        effective_tenant = tenant_id or GLOBAL_KNOWLEDGE_TENANT
        rows = self._conn.execute(
            """
            SELECT d.document_id, d.tenant_id, d.title, d.document_type, d.domains, d.tags,
                   d.current_version_no, d.status, d.owner_user_id,
                   v.knowledge_version_id, c.chunk_id, c.content, c.locator
            FROM platform_knowledge_documents d
            JOIN platform_knowledge_versions v
              ON v.tenant_id = d.tenant_id AND v.document_id = d.document_id
             AND v.version_no = d.current_version_no
            JOIN platform_knowledge_chunks c
              ON c.tenant_id = v.tenant_id AND c.knowledge_version_id = v.knowledge_version_id
            WHERE d.status = 'active' AND d.tenant_id IN (?, ?)
              AND v.processing_status = 'ready' AND v.published_at IS NOT NULL
            """,
            (GLOBAL_KNOWLEDGE_TENANT, effective_tenant),
        ).fetchall()
        query_text = str(query or "").strip().lower()
        query_terms = _search_terms(query_text)
        best_by_document: dict[tuple[str, str], KnowledgeHit] = {}
        for row in rows:
            row_domains = tuple(_load_json(row["domains"], []))
            if domains and not set(domains).intersection(row_domains):
                continue
            tags = tuple(_load_json(row["tags"], []))
            title = str(row["title"])
            content = str(row["content"])
            haystack = f"{title} {content} {' '.join(tags)}".lower()
            matched = tuple(term for term in query_terms if term and term in haystack)
            exact_bonus = 1.0 if query_text and query_text in haystack else 0.0
            title_bonus = 0.5 if query_text and query_text in title.lower() else 0.0
            if query_terms and not matched and not exact_bonus:
                continue
            score = min(1.0, (len(matched) / max(len(query_terms), 1)) * 0.7 + exact_bonus * 0.2 + title_bonus * 0.1)
            document = KnowledgeDocument(
                doc_id=str(row["document_id"]),
                title=title,
                content=content,
                tenant_id=None if row["tenant_id"] == GLOBAL_KNOWLEDGE_TENANT else str(row["tenant_id"]),
                domains=row_domains,
                source_type=str(row["document_type"]),
                tags=tags,
                version_no=int(row["current_version_no"]),
                status=str(row["status"]),
                owner_user_id=str(row["owner_user_id"]),
            )
            hit = KnowledgeHit(
                document=document,
                score=score,
                matched_terms=matched,
                chunk_id=str(row["chunk_id"]),
                knowledge_version_id=str(row["knowledge_version_id"]),
                locator=_load_json(row["locator"], {}),
            )
            key = (str(row["tenant_id"]), str(row["document_id"]))
            current = best_by_document.get(key)
            if current is None or hit.score > current.score:
                best_by_document[key] = hit
        return sorted(best_by_document.values(), key=lambda hit: (hit.score, hit.document.title), reverse=True)[: max(1, min(int(limit), 50))]

    def create_citation(
        self,
        tenant_id: str,
        hit: KnowledgeHit,
        resource_type: str,
        resource_id: str,
        created_by: str,
    ) -> dict[str, Any]:
        if not hit.chunk_id:
            raise ValueError("knowledge_chunk_id_required")
        citation_id = f"kc_{uuid4().hex}"
        quote_hash = hashlib.sha256(hit.document.content.encode("utf-8")).hexdigest()
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_knowledge_citations(
                    tenant_id, citation_id, chunk_tenant_id, chunk_id, resource_type, resource_id,
                    quote_hash, locator, relevance_score, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, chunk_id, resource_type, resource_id) DO UPDATE SET
                    quote_hash = excluded.quote_hash,
                    locator = excluded.locator,
                    relevance_score = excluded.relevance_score
                """,
                (
                    tenant_id,
                    citation_id,
                    hit.document.tenant_id or GLOBAL_KNOWLEDGE_TENANT,
                    hit.chunk_id,
                    resource_type,
                    resource_id,
                    quote_hash,
                    _json(hit.locator),
                    max(0, min(float(hit.score), 1)),
                    created_by,
                    now,
                ),
            )
        stored = self._conn.execute(
            """
            SELECT citation_id FROM platform_knowledge_citations
            WHERE tenant_id = ? AND chunk_id = ? AND resource_type = ? AND resource_id = ?
            """,
            (tenant_id, hit.chunk_id, resource_type, resource_id),
        ).fetchone()
        actual_citation_id = str(stored["citation_id"]) if stored else citation_id
        return {
            "citation_id": actual_citation_id,
            "chunk_id": hit.chunk_id,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "quote_hash": quote_hash,
            "locator": hit.locator,
        }

    def create_attachment(
        self,
        tenant_id: str,
        *,
        artifact_id: str,
        owner_user_id: str,
        resource_id: str,
        file_name: str,
        detected_content_type: str,
        scan_status: str,
        processing_status: str,
        classification: str,
        resource_type: str = "knowledge_document",
    ) -> dict[str, Any]:
        resource_type = str(resource_type or "").strip()
        if resource_type not in {"knowledge_document", "weekly_report_image"}:
            raise ValueError("unsupported_attachment_resource_type")
        attachment_id = f"fa_{uuid4().hex}"
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_file_attachments(
                    tenant_id, attachment_id, artifact_id, owner_user_id, resource_type,
                    resource_id, file_name, detected_content_type, scan_status,
                    processing_status, classification, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    attachment_id,
                    artifact_id,
                    owner_user_id,
                    resource_type,
                    resource_id,
                    file_name,
                    detected_content_type,
                    scan_status,
                    processing_status,
                    classification,
                    owner_user_id,
                    now,
                    now,
                ),
            )
        row = self._conn.execute(
            "SELECT * FROM platform_file_attachments WHERE tenant_id = ? AND attachment_id = ?",
            (tenant_id, attachment_id),
        ).fetchone()
        assert row is not None
        return dict(row)

    def get_attachment(self, tenant_id: str, attachment_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM platform_file_attachments WHERE tenant_id = ? AND attachment_id = ?",
            (tenant_id, attachment_id),
        ).fetchone()
        if not row:
            raise KeyError("file_attachment_not_found")
        return dict(row)

    def update_attachment_processing(
        self,
        tenant_id: str,
        attachment_id: str,
        processing_status: str,
        *,
        error_code: str = "",
    ) -> dict[str, Any]:
        if processing_status not in {"pending", "processing", "ready", "failed"}:
            raise ValueError("invalid_attachment_processing_status")
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE platform_file_attachments
                SET processing_status = ?, processing_error = ?, updated_at = ?
                WHERE tenant_id = ? AND attachment_id = ?
                """,
                (processing_status, str(error_code or "")[:200], _utcnow(), tenant_id, attachment_id),
            )
        if cursor.rowcount != 1:
            raise KeyError("file_attachment_not_found")
        return self.get_attachment(tenant_id, attachment_id)

    def ensure_artifact_reference(self, tenant_id: str, artifact_id: str) -> None:
        row = self._conn.execute(
            "SELECT 1 FROM platform_data_artifacts WHERE tenant_id = ? AND artifact_id = ?",
            (tenant_id, artifact_id),
        ).fetchone()
        if row:
            return
        columns = {
            str(item["name"])
            for item in self._conn.execute("PRAGMA table_info(platform_data_artifacts)").fetchall()
        }
        if columns == {"tenant_id", "artifact_id"}:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO platform_data_artifacts(tenant_id, artifact_id) VALUES (?, ?)",
                    (tenant_id, artifact_id),
                )
            return
        raise KeyError("knowledge_artifact_reference_not_found")

    def _write_document_version(
        self,
        *,
        tenant_id: str,
        document_id: str,
        document_code: str,
        title: str,
        document_type: str,
        owner_user_id: str,
        classification: str,
        domains: tuple[str, ...],
        tags: tuple[str, ...],
        content: str,
        language: str,
        parser_name: str,
        created_by: str,
        version_no: int,
        status: str,
        published: bool,
        source_attachment_id: str | None = None,
        content_artifact_id: str | None = None,
    ) -> None:
        now = _utcnow()
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        knowledge_version_id = f"kv_{uuid4().hex}"
        chunks = _chunk_text(content)
        if not chunks:
            raise ValueError("knowledge_content_has_no_indexable_text")
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_knowledge_documents(
                    tenant_id, document_id, document_code, title, document_type,
                    owner_user_id, classification, domains, tags, current_version_no,
                    status, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, document_id) DO UPDATE SET
                    title = excluded.title,
                    document_type = excluded.document_type,
                    classification = excluded.classification,
                    domains = excluded.domains,
                    tags = excluded.tags,
                    current_version_no = excluded.current_version_no,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    tenant_id,
                    document_id,
                    document_code,
                    title,
                    document_type,
                    owner_user_id,
                    classification,
                    _json(domains),
                    _json(tags),
                    version_no,
                    status,
                    created_by,
                    now,
                    now,
                ),
            )
            self._conn.execute(
                """
                INSERT INTO platform_knowledge_versions(
                    tenant_id, knowledge_version_id, document_id, version_no,
                    source_attachment_id, content_artifact_id, content_hash, language,
                    parser_name, processing_status, published_at, reviewed_by,
                    created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    knowledge_version_id,
                    document_id,
                    version_no,
                    source_attachment_id,
                    content_artifact_id,
                    content_hash,
                    language,
                    parser_name,
                    now if published else None,
                    created_by if published else None,
                    created_by,
                    now,
                ),
            )
            for chunk_no, chunk in enumerate(chunks):
                chunk_hash = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
                self._conn.execute(
                    """
                    INSERT INTO platform_knowledge_chunks(
                        tenant_id, chunk_id, knowledge_version_id, chunk_no, content,
                        content_hash, token_count, heading_path, keywords, locator, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?)
                    """,
                    (
                        tenant_id,
                        f"kch_{uuid4().hex}",
                        knowledge_version_id,
                        chunk_no,
                        chunk,
                        chunk_hash,
                        len(_search_terms(chunk.lower())),
                        _json(_search_terms(chunk.lower())[:20]),
                        _json({"chunk_no": chunk_no, "char_length": len(chunk)}),
                        now,
                    ),
                )

    def _migrate_legacy_rows(self) -> None:
        if not self._table_exists("platform_knowledge_documents_legacy"):
            return
        rows = self._conn.execute(
            """
            SELECT doc_id, tenant_id, title, content, source_type, domains, tags
            FROM platform_knowledge_documents_legacy
            """
        ).fetchall()
        for row in rows:
            try:
                self.add(
                    KnowledgeDocument(
                        doc_id=str(row["doc_id"]),
                        title=str(row["title"]),
                        content=str(row["content"]),
                        tenant_id=str(row["tenant_id"]) if row["tenant_id"] else None,
                        domains=tuple(_load_json(row["domains"], [])),
                        source_type=str(row["source_type"] or "other"),
                        tags=tuple(_load_json(row["tags"], [])),
                    )
                )
            except sqlite3.IntegrityError:
                continue

    def _table_exists(self, table_name: str) -> bool:
        return bool(
            self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone()
        )


class InMemoryKnowledgeStore(SQLiteKnowledgeStore):
    def __init__(self, documents: list[KnowledgeDocument] | None = None) -> None:
        self.db_path = ":memory:"
        self._conn = connect_sqlite(":memory:")
        self._conn.row_factory = sqlite3.Row
        self.init_schema()
        for document in documents or []:
            self.add(document)


def _document_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["domains"] = _load_json(result.get("domains"), [])
    result["tags"] = _load_json(result.get("tags"), [])
    return result


def _chunk_text(content: str, size: int = 1200, overlap: int = 120) -> list[str]:
    normalized = "\n".join(line.rstrip() for line in content.replace("\r\n", "\n").split("\n")).strip()
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + size)
        if end < len(normalized):
            boundary = max(normalized.rfind("\n", start + size // 2, end), normalized.rfind("。", start + size // 2, end))
            if boundary > start:
                end = boundary + 1
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _search_terms(value: str) -> list[str]:
    terms: list[str] = []
    for token in re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", value.lower()):
        if token not in terms:
            terms.append(token)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 2:
            for index in range(len(token) - 1):
                pair = token[index : index + 2]
                if pair not in terms:
                    terms.append(pair)
    return terms


def _document_type(value: Any) -> str:
    normalized = str(value or "other").strip().lower()
    aliases = {"document": "other", "rule": "business_rule", "knowledge": "other"}
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in DOCUMENT_TYPES else "other"


def _required_text(value: Any, field: str, max_length: int) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > max_length:
        raise ValueError(f"invalid_{field}")
    return normalized


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [item.strip() for item in value.split(",")]
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


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
