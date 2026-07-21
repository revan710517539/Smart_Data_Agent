from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    memory_type: str
    tenant_id: str
    subject: str
    content: dict[str, Any]
    source_trace_id: str | None = None
    confidence: float = 0.0
    verified_status: str = "draft"
    subject_type: str = "tenant"
    subject_id: str = ""
    title: str = ""
    weight: float = 1.0
    expires_at: str | None = None
    supersedes_memory_id: str | None = None
    evidence_type: str | None = None
    evidence_id: str | None = None
    evidence_hash: str | None = None
    created_by: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
