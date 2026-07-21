from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GraphEntity:
    entity_id: str
    entity_type: str
    name: str


@dataclass(frozen=True)
class GraphEdge:
    source_id: str
    relation: str
    target_id: str

