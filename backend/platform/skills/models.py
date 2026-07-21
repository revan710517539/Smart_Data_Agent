from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from backend.platform.tenancy import ExecutionContext


SkillRuntimeType = Literal["python", "http_api", "mcp", "supersonic", "sandbox"]
SkillHandler = Callable[["SkillRequest"], "SkillResult"]


@dataclass(frozen=True)
class SkillSpec:
    skill_id: str
    name: str
    skill_type: str
    description: str
    input_schema: dict[str, str]
    output_schema: dict[str, str]
    permission_scope: tuple[str, ...]
    risk_level: Literal["low", "medium", "high"]
    runtime_type: SkillRuntimeType
    version: str = "1.0.0"
    owner: str = "data-platform"
    status: Literal["active", "disabled"] = "active"
    timeout_seconds: int = 60
    max_retries: int = 0
    requires_approval: bool = False


@dataclass(frozen=True)
class SkillRequest:
    skill_id: str
    context: ExecutionContext
    inputs: dict[str, Any]
    trace_id: str | None = None
    agent_id: str | None = None
    approval_id: str | None = None


@dataclass(frozen=True)
class SkillResult:
    skill_id: str
    output: dict[str, Any]
    audit: dict[str, Any] = field(default_factory=dict)
