from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class KnowledgeDocument:
    doc_id: str
    title: str
    content: str
    tenant_id: str | None = None
    domains: tuple[str, ...] = ()
    source_type: str = "document"
    tags: tuple[str, ...] = ()
    version_no: int = 1
    status: str = "active"
    owner_user_id: str = "system"


@dataclass(frozen=True)
class KnowledgeHit:
    document: KnowledgeDocument
    score: float
    matched_terms: tuple[str, ...] = field(default_factory=tuple)
    chunk_id: str = ""
    knowledge_version_id: str = ""
    locator: dict[str, object] = field(default_factory=dict)
