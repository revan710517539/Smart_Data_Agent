from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SemanticQueryRequest:
    question: str
    tenant_id: str
    user_id: str
    dataset_id: str | None = None
    metrics: tuple[str, ...] = ()
    dimensions: tuple[str, ...] = ()
    filters: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    limit: int = 20
    sort_direction: str = "desc"


@dataclass(frozen=True)
class SemanticQueryResult:
    sql: str
    data: list[dict[str, Any]]
    chart_spec: dict[str, Any]
    semantic_info: dict[str, Any]
    parameters: dict[str, Any] = field(default_factory=dict)
