from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

CapabilityScope = Literal["user", "role", "org", "tenant", "platform"]
CapabilityKind = Literal["executable", "procedure", "memory", "plugin", "draft"]
CapabilityStatus = Literal["candidate", "review", "active", "disabled", "rejected", "superseded"]
RuntimeType = Literal[
    "python",
    "http_api",
    "mcp",
    "supersonic",
    "sandbox",
    "procedure",
    "context",
    "llm",
    "draft_provider",
    "graph",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


@dataclass(frozen=True)
class Capability:
    capability_id: str
    kind: CapabilityKind
    runtime_type: RuntimeType
    tenant_id: str
    owner_scope: CapabilityScope
    owner_id: str
    title: str = ""
    description: str = ""
    version: str = "1.0.0"
    status: CapabilityStatus = "active"
    trigger: dict[str, Any] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)
    fingerprint: str = ""
    permission_scope: tuple[str, ...] = ()
    created_by: str = ""

    def index_entry(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "kind": self.kind,
            "runtime_type": self.runtime_type,
            "owner_scope": self.owner_scope,
            "owner_id": self.owner_id,
            "title": self.title,
            "description": self.description,
            "version": self.version,
            "status": self.status,
            "trigger": dict(self.trigger),
            "fingerprint": self.fingerprint,
            "permission_scope": list(self.permission_scope),
        }


@dataclass(frozen=True)
class CapabilityPack:
    snapshot_id: str
    tenant_id: str
    user_id: str
    compiled_at: str
    entries: tuple[dict[str, Any], ...]
    applied_ids: tuple[str, ...] = ()

    def ids(self) -> tuple[str, ...]:
        return tuple(str(item["capability_id"]) for item in self.entries)


@dataclass
class RouteDecision:
    intent_rule_id: str
    task_type: str
    dataset_id: str
    metrics: tuple[str, ...]
    dimensions: tuple[str, ...]
    chart_types: tuple[str, ...]
    capability_ids: tuple[str, ...]
    planning_source: str = "runtime_router"


@dataclass
class Episode:
    episode_id: str
    tenant_id: str
    user_id: str
    session_id: str = ""
    parent_episode_id: str | None = None
    status: str = "running"
    turn_count: int = 1
    pack_snapshot_id: str = ""
    question: str = ""
    created_at: str = field(default_factory=utc_now)
    detail: dict[str, Any] = field(default_factory=dict)
