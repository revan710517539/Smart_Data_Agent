from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class RuntimeEvent:
    event_type: str
    trace_id: str
    tenant_id: str
    user_id: str
    status: str
    latency_ms: int
    fallback_used: bool = False
    detail: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: f"evt_{uuid4().hex[:12]}")
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
