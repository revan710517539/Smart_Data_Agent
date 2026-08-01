from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from .models import MemoryRecord
from .store import canonical_memory_type


class MemoryService:
    def __init__(self, store: Any) -> None:
        self.store = store

    def create_candidate(self, tenant_id: str, payload: dict[str, Any], actor_user_id: str) -> dict[str, Any]:
        content = payload.get("content")
        if not isinstance(content, dict) or not content:
            raise ValueError("memory_content_must_be_non_empty_object")
        memory_type = canonical_memory_type(str(payload.get("memory_type") or "other"))
        subject_type = str(payload.get("subject_type") or "user").strip()
        if subject_type not in {"user", "role", "org", "tenant"}:
            raise ValueError("invalid_memory_subject_type")
        subject_id = str(payload.get("subject_id") or (actor_user_id if subject_type == "user" else tenant_id)).strip()
        evidence = payload.get("evidence", {})
        if evidence and not isinstance(evidence, dict):
            raise ValueError("memory_evidence_must_be_object")
        evidence = dict(evidence or {})
        evidence_hash = str(evidence.get("evidence_hash") or "")
        if evidence and not evidence_hash:
            evidence_hash = hashlib.sha256(
                json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
        memory_id = str(payload.get("memory_id") or f"mem_{uuid4().hex}")
        record = MemoryRecord(
            memory_id=memory_id,
            memory_type=memory_type,
            tenant_id=tenant_id,
            subject=str(payload.get("title") or memory_type),
            title=str(payload.get("title") or memory_type)[:500],
            content=content,
            source_trace_id=str(payload.get("source_trace_id") or "") or None,
            confidence=max(0, min(float(payload.get("confidence", 0.7)), 1)),
            verified_status="candidate",
            subject_type=subject_type,
            subject_id=subject_id,
            weight=max(0, float(payload.get("weight", 1))),
            expires_at=str(payload.get("expires_at") or "") or None,
            supersedes_memory_id=str(payload.get("supersedes_memory_id") or "") or None,
            evidence_type=str(evidence.get("evidence_type") or "") or None,
            evidence_id=str(evidence.get("evidence_id") or "") or None,
            evidence_hash=evidence_hash or None,
            created_by=actor_user_id,
        )
        if not self.store.write(record):
            raise ValueError("memory_candidate_rejected_or_duplicate")
        return self.store.get(tenant_id, memory_id)

    def review_candidate(
        self,
        tenant_id: str,
        memory_id: str,
        decision: str,
        actor_user_id: str,
        comments: str = "",
    ) -> dict[str, Any]:
        return self.store.review(tenant_id, memory_id, decision, actor_user_id, comments=comments)

    def list_candidates(self, tenant_id: str) -> list[dict[str, Any]]:
        return self.store.list_candidates(tenant_id)

    def get(self, tenant_id: str, memory_id: str) -> dict[str, Any]:
        return self.store.get(tenant_id, memory_id)

    def list_active(self, tenant_id: str, actor_user_id: str) -> list[dict[str, Any]]:
        records = self.store.search(tenant_id, statuses=("active",), limit=200)
        return [
            self.store.get(tenant_id, record.memory_id)
            for record in records
            if record.subject_type == "tenant"
            or (record.subject_type == "user" and record.subject_id == actor_user_id)
        ]
