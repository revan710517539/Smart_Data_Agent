from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator
from uuid import uuid4

from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.postgresql import PostgreSQLConnectionPool

from .models import KnowledgeDocument, KnowledgeHit
from .store import (
    CLASSIFICATIONS,
    GLOBAL_KNOWLEDGE_TENANT,
    _chunk_text,
    _document_type,
    _required_text,
    _search_terms,
    _string_tuple,
)


class PostgreSQLKnowledgeStore:
    """Versioned, chunk-indexed and four-eyes production knowledge store."""

    def __init__(self, pool: PostgreSQLConnectionPool, *, owns_pool: bool = False) -> None:
        self.pool = pool
        self.owns_pool = owns_pool

    def close(self) -> None:
        if self.owns_pool:
            self.pool.close()

    def add(self, document: KnowledgeDocument) -> None:
        tenant_id = document.tenant_id or GLOBAL_KNOWLEDGE_TENANT
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT d.document_id, d.current_version_no, v.content_hash
                    FROM platform_knowledge_documents d
                    LEFT JOIN platform_knowledge_versions v
                      ON v.document_id = d.document_id AND v.version_no = d.current_version_no
                    WHERE d.tenant_id = %s AND d.document_key = %s
                    """,
                    (tenant_key, document.doc_id),
                )
                existing = cursor.fetchone()
        content_hash = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
        if existing and str(_value(existing, "content_hash", 2) or "") == content_hash:
            return
        version_no = int(_value(existing, "current_version_no", 1) or 0) + 1 if existing else 1
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
        classification = str(payload.get("classification") or "internal").strip()
        if classification not in CLASSIFICATIONS:
            raise ValueError("invalid_knowledge_classification")
        self._write_document_version(
            tenant_id=tenant_id,
            document_id=document_id,
            document_code=document_code,
            title=title,
            document_type=_document_type(payload.get("document_type", payload.get("source_type", "other"))),
            owner_user_id=created_by,
            classification=classification,
            domains=_string_tuple(payload.get("domains", ())),
            tags=_string_tuple(payload.get("tags", ())),
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
            version_no=int(document["current_version_no"]) + 1,
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
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            reviewer_key = PostgreSQLIdentityResolver.user_id(connection, reviewer)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT d.document_id, d.status, d.current_version_no,
                           v.knowledge_version_id, v.created_by
                    FROM platform_knowledge_documents d
                    JOIN platform_knowledge_versions v
                      ON v.document_id = d.document_id AND v.version_no = d.current_version_no
                    WHERE d.tenant_id = %s AND d.document_key = %s
                    FOR UPDATE OF d, v
                    """,
                    (tenant_key, document_id),
                )
                row = cursor.fetchone()
                if not row:
                    raise KeyError("knowledge_document_not_found")
                if normalized != "archive" and str(_value(row, "status", 1)) != "review":
                    raise ValueError("knowledge_document_is_not_in_review")
                if normalized == "approve" and _value(row, "created_by", 4) == reviewer_key:
                    raise PermissionError("four_eyes_knowledge_review_required")
                status = {"approve": "active", "reject": "failed", "archive": "archived"}[normalized]
                cursor.execute(
                    "UPDATE platform_knowledge_documents SET status = %s, updated_at = now(), lock_version = lock_version + 1 WHERE document_id = %s",
                    (status, _value(row, "document_id", 0)),
                )
                if normalized == "approve":
                    cursor.execute(
                        """
                        UPDATE platform_knowledge_versions
                        SET published_at = now(), reviewed_by = %s, updated_at = now(),
                            lock_version = lock_version + 1
                        WHERE knowledge_version_id = %s
                        """,
                        (reviewer_key, _value(row, "knowledge_version_id", 3)),
                    )
        return self.get_document(tenant_id, document_id)

    def get_document(self, tenant_id: str, document_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            rows = self._document_rows(connection, "d.tenant_id = %s AND d.document_key = %s", (tenant_key, document_id))
        if not rows:
            raise KeyError("knowledge_document_not_found")
        return self._document_from_row(rows[0])

    def list_documents(self, tenant_id: str, include_archived: bool = False) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            where = "d.tenant_id = %s" + ("" if include_archived else " AND d.status <> 'archived'")
            rows = self._document_rows(connection, where, (tenant_key,))
        return [self._document_from_row(row) for row in rows]

    def search(
        self,
        query: str,
        tenant_id: str | None = None,
        domains: tuple[str, ...] = (),
        limit: int = 5,
    ) -> list[KnowledgeHit]:
        effective_tenant = tenant_id or GLOBAL_KNOWLEDGE_TENANT
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, effective_tenant)
            global_key = PostgreSQLIdentityResolver.tenant_id(connection, GLOBAL_KNOWLEDGE_TENANT, required=False)
            tenant_keys = [tenant_key] + ([global_key] if global_key is not None and global_key != tenant_key else [])
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT d.document_key, t.tenant_code, d.title, d.document_type,
                           d.domains, d.tags, d.current_version_no, d.status,
                           owner.external_subject AS owner_user_id, v.version_key,
                           c.chunk_key, c.content, c.locator
                    FROM platform_knowledge_documents d
                    JOIN platform_tenants t ON t.tenant_id = d.tenant_id
                    JOIN platform_user_profiles owner ON owner.user_id = d.owner_user_id
                    JOIN platform_knowledge_versions v
                      ON v.document_id = d.document_id AND v.version_no = d.current_version_no
                    JOIN platform_knowledge_chunks c ON c.knowledge_version_id = v.knowledge_version_id
                    WHERE d.status = 'active' AND d.tenant_id = ANY(%s)
                      AND v.processing_status = 'ready' AND v.published_at IS NOT NULL
                    """,
                    (tenant_keys,),
                )
                rows = cursor.fetchall()
        query_text = str(query or "").strip().lower()
        query_terms = _search_terms(query_text)
        best: dict[tuple[str, str], KnowledgeHit] = {}
        for row in rows:
            row_domains = tuple(_json_value(_value(row, "domains", 4), []))
            if domains and not set(domains).intersection(row_domains):
                continue
            tags = tuple(_json_value(_value(row, "tags", 5), []))
            title = str(_value(row, "title", 2))
            content = str(_value(row, "content", 11))
            haystack = f"{title} {content} {' '.join(tags)}".lower()
            matched = tuple(term for term in query_terms if term and term in haystack)
            exact_bonus = 1.0 if query_text and query_text in haystack else 0.0
            title_bonus = 0.5 if query_text and query_text in title.lower() else 0.0
            if query_terms and not matched and not exact_bonus:
                continue
            score = min(1.0, (len(matched) / max(len(query_terms), 1)) * 0.7 + exact_bonus * 0.2 + title_bonus * 0.1)
            tenant_code = str(_value(row, "tenant_code", 1))
            document = KnowledgeDocument(
                doc_id=str(_value(row, "document_key", 0)), title=title, content=content,
                tenant_id=None if tenant_code == GLOBAL_KNOWLEDGE_TENANT else tenant_code,
                domains=row_domains, source_type=str(_value(row, "document_type", 3)), tags=tags,
                version_no=int(_value(row, "current_version_no", 6)),
                status=str(_value(row, "status", 7)), owner_user_id=str(_value(row, "owner_user_id", 8)),
            )
            hit = KnowledgeHit(
                document=document, score=score, matched_terms=matched,
                chunk_id=str(_value(row, "chunk_key", 10)),
                knowledge_version_id=str(_value(row, "version_key", 9)),
                locator=dict(_json_value(_value(row, "locator", 12), {})),
            )
            key = (tenant_code, document.doc_id)
            if key not in best or hit.score > best[key].score:
                best[key] = hit
        return sorted(best.values(), key=lambda hit: (hit.score, hit.document.title), reverse=True)[: max(1, min(int(limit), 50))]

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
        citation_key = f"kc_{uuid4().hex}"
        quote_hash = hashlib.sha256(hit.document.content.encode("utf-8")).hexdigest()
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, created_by)
            chunk_tenant_code = hit.document.tenant_id or GLOBAL_KNOWLEDGE_TENANT
            chunk_tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, chunk_tenant_code)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT chunk_id FROM platform_knowledge_chunks WHERE tenant_id = %s AND chunk_key = %s",
                    (chunk_tenant_key, hit.chunk_id),
                )
                chunk = cursor.fetchone()
                if not chunk:
                    raise KeyError("knowledge_chunk_not_found")
                chunk_id = _value(chunk, "chunk_id", 0)
                cursor.execute(
                    """
                    INSERT INTO platform_knowledge_citations(
                        tenant_id, citation_key, chunk_id, resource_type, resource_id,
                        quote_hash, locator, relevance_score, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    ON CONFLICT (tenant_id, chunk_id, resource_type, resource_id) DO UPDATE SET
                        quote_hash = EXCLUDED.quote_hash, locator = EXCLUDED.locator,
                        relevance_score = EXCLUDED.relevance_score, updated_at = now(),
                        lock_version = platform_knowledge_citations.lock_version + 1
                    RETURNING citation_key
                    """,
                    (
                        tenant_key, citation_key, chunk_id, resource_type[:40], resource_id[:300],
                        quote_hash, _json(hit.locator), max(0, min(float(hit.score), 1)), actor_key,
                    ),
                )
                actual_key = str(_value(cursor.fetchone(), "citation_key", 0))
        return {
            "citation_id": actual_key, "chunk_id": hit.chunk_id,
            "resource_type": resource_type, "resource_id": resource_id,
            "quote_hash": quote_hash, "locator": hit.locator,
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
        if resource_type not in {"knowledge_document", "weekly_report_image"}:
            raise ValueError("unsupported_attachment_resource_type")
        attachment_key = f"fa_{uuid4().hex}"
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            owner_key = PostgreSQLIdentityResolver.user_id(connection, owner_user_id)
            artifact_key = self._artifact_id(connection, tenant_key, artifact_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_file_attachments(
                        tenant_id, attachment_key, artifact_id, owner_user_id, resource_type,
                        resource_id, file_name, detected_content_type, scan_status,
                        processing_status, classification, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        tenant_key, attachment_key, artifact_key, owner_key, resource_type,
                        resource_id[:300], file_name[:500], detected_content_type[:200],
                        scan_status, processing_status, classification, owner_key,
                    ),
                )
        return self.get_attachment(tenant_id, attachment_key)

    def get_attachment(self, tenant_id: str, attachment_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._attachment_select() + " WHERE f.tenant_id = %s AND f.attachment_key = %s", (tenant_key, attachment_id))
                row = cursor.fetchone()
        if not row:
            raise KeyError("file_attachment_not_found")
        return self._attachment_from_row(row)

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
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_file_attachments
                    SET processing_status = %s, processing_error = %s, updated_at = now(),
                        lock_version = lock_version + 1
                    WHERE tenant_id = %s AND attachment_key = %s
                    """,
                    (processing_status, str(error_code or "")[:200], tenant_key, attachment_id),
                )
                if cursor.rowcount != 1:
                    raise KeyError("file_attachment_not_found")
        return self.get_attachment(tenant_id, attachment_id)

    def ensure_artifact_reference(self, tenant_id: str, artifact_id: str) -> None:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            self._artifact_id(connection, tenant_key, artifact_id)

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
        chunks = _chunk_text(content)
        if not chunks:
            raise ValueError("knowledge_content_has_no_indexable_text")
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        version_key = f"kv_{uuid4().hex}"
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            owner_key = PostgreSQLIdentityResolver.user_id(connection, owner_user_id)
            creator_key = PostgreSQLIdentityResolver.user_id(connection, created_by)
            attachment_key = self._attachment_id(connection, tenant_key, source_attachment_id) if source_attachment_id else None
            artifact_key = self._artifact_id(connection, tenant_key, content_artifact_id) if content_artifact_id else None
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_knowledge_documents(
                        tenant_id, document_key, document_code, title, document_type,
                        owner_user_id, classification, domains, tags, current_version_no,
                        status, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
                    ON CONFLICT (tenant_id, document_key) DO UPDATE SET
                        title = EXCLUDED.title, document_type = EXCLUDED.document_type,
                        classification = EXCLUDED.classification, domains = EXCLUDED.domains,
                        tags = EXCLUDED.tags, current_version_no = EXCLUDED.current_version_no,
                        status = EXCLUDED.status, updated_at = now(),
                        lock_version = platform_knowledge_documents.lock_version + 1
                    RETURNING document_id
                    """,
                    (
                        tenant_key, document_id[:200], document_code[:200], title, document_type,
                        owner_key, classification, _json(domains), _json(tags), version_no, status, creator_key,
                    ),
                )
                internal_document_id = _value(cursor.fetchone(), "document_id", 0)
                cursor.execute(
                    """
                    INSERT INTO platform_knowledge_versions(
                        tenant_id, version_key, document_id, version_no, source_attachment_id,
                        content_artifact_id, content_hash, language, parser_name,
                        processing_status, published_at, reviewed_by, created_by
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, 'ready',
                        CASE WHEN %s THEN now() END, CASE WHEN %s THEN %s END, %s
                    ) RETURNING knowledge_version_id
                    """,
                    (
                        tenant_key, version_key, internal_document_id, version_no,
                        attachment_key, artifact_key, content_hash, language, parser_name,
                        published, published, creator_key, creator_key,
                    ),
                )
                version_id = _value(cursor.fetchone(), "knowledge_version_id", 0)
                for chunk_no, chunk in enumerate(chunks):
                    chunk_hash = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
                    cursor.execute(
                        """
                        INSERT INTO platform_knowledge_chunks(
                            tenant_id, chunk_key, knowledge_version_id, chunk_no, content,
                            content_hash, token_count, heading_path, keywords, locator, created_by
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, '[]'::jsonb, %s::jsonb, %s::jsonb, %s)
                        """,
                        (
                            tenant_key, f"kch_{uuid4().hex}", version_id, chunk_no, chunk,
                            chunk_hash, len(_search_terms(chunk.lower())),
                            _json(_search_terms(chunk.lower())[:20]),
                            _json({"chunk_no": chunk_no, "char_length": len(chunk)}), creator_key,
                        ),
                    )

    @staticmethod
    def _document_rows(connection: Any, where: str, params: tuple[Any, ...]) -> list[Any]:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT d.document_key, t.tenant_code, d.document_code, d.title,
                       d.document_type, owner.external_subject AS owner_user_id,
                       d.classification, d.domains, d.tags, d.current_version_no,
                       d.status, d.created_at, d.updated_at
                FROM platform_knowledge_documents d
                JOIN platform_tenants t ON t.tenant_id = d.tenant_id
                JOIN platform_user_profiles owner ON owner.user_id = d.owner_user_id
                WHERE {where}
                ORDER BY d.updated_at DESC
                """,
                params,
            )
            return list(cursor.fetchall())

    @staticmethod
    def _document_from_row(row: Any) -> dict[str, Any]:
        return {
            "document_id": str(_value(row, "document_key", 0)),
            "tenant_id": str(_value(row, "tenant_code", 1)),
            "document_code": str(_value(row, "document_code", 2)),
            "title": str(_value(row, "title", 3)),
            "document_type": str(_value(row, "document_type", 4)),
            "owner_user_id": str(_value(row, "owner_user_id", 5)),
            "classification": str(_value(row, "classification", 6)),
            "domains": list(_json_value(_value(row, "domains", 7), [])),
            "tags": list(_json_value(_value(row, "tags", 8), [])),
            "current_version_no": int(_value(row, "current_version_no", 9)),
            "status": str(_value(row, "status", 10)),
            "created_at": _iso(_value(row, "created_at", 11)),
            "updated_at": _iso(_value(row, "updated_at", 12)),
        }

    @staticmethod
    def _attachment_select() -> str:
        return """
            SELECT f.attachment_key, t.tenant_code, a.artifact_key,
                   owner.external_subject AS owner_user_id, f.resource_type, f.resource_id,
                   f.file_name, f.detected_content_type, f.scan_status,
                   f.processing_status, f.processing_error, f.classification,
                   f.created_at, f.updated_at
            FROM platform_file_attachments f
            JOIN platform_tenants t ON t.tenant_id = f.tenant_id
            JOIN platform_data_artifacts a ON a.artifact_id = f.artifact_id
            JOIN platform_user_profiles owner ON owner.user_id = f.owner_user_id
        """

    @staticmethod
    def _attachment_from_row(row: Any) -> dict[str, Any]:
        keys = (
            "attachment_id", "tenant_id", "artifact_id", "owner_user_id",
            "resource_type", "resource_id", "file_name", "detected_content_type",
            "scan_status", "processing_status", "processing_error", "classification",
            "created_at", "updated_at",
        )
        db_keys = (
            "attachment_key", "tenant_code", "artifact_key", "owner_user_id",
            "resource_type", "resource_id", "file_name", "detected_content_type",
            "scan_status", "processing_status", "processing_error", "classification",
            "created_at", "updated_at",
        )
        return {
            key: _iso(value) if isinstance(value, datetime) else value
            for index, (key, db_key) in enumerate(zip(keys, db_keys))
            for value in [_value(row, db_key, index)]
        }

    @staticmethod
    def _artifact_id(connection: Any, tenant_key: Any, artifact_key: str | None) -> Any:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT artifact_id FROM platform_data_artifacts WHERE tenant_id = %s AND artifact_key = %s AND status = 'active'",
                (tenant_key, artifact_key),
            )
            row = cursor.fetchone()
        if not row:
            raise KeyError("knowledge_artifact_reference_not_found")
        return _value(row, "artifact_id", 0)

    @staticmethod
    def _attachment_id(connection: Any, tenant_key: Any, attachment_key: str | None) -> Any:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT attachment_id FROM platform_file_attachments WHERE tenant_id = %s AND attachment_key = %s",
                (tenant_key, attachment_key),
            )
            row = cursor.fetchone()
        if not row:
            raise KeyError("file_attachment_not_found")
        return _value(row, "attachment_id", 0)

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self.pool.connection() as connection:
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value or "")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value) if isinstance(value, str) else value


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]
