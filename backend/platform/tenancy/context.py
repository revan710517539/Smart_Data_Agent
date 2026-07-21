from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExecutionContext:
    """Request-scoped identity, tenant, page, and runtime context."""

    user_id: str
    tenant_id: str
    roles: tuple[str, ...] = ()
    channel: str = "web"
    locale: str = "zh-CN"
    page_context: dict[str, Any] = field(default_factory=dict)

