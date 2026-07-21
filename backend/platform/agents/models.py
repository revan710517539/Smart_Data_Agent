from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    name: str
    agent_type: str
    description: str
    allowed_skills: tuple[str, ...]
    prompt_template_id: str | None = None
    memory_policy: str = "read_write_reviewed"
    status: str = "active"


@dataclass(frozen=True)
class AgentGroupSpec:
    group_id: str
    group_name: str
    mission: str
    controller_agent: str
    agents: tuple[AgentSpec, ...]
    stage_gates: tuple[str, ...]


@dataclass
class AgentGroupRun:
    group_id: str
    gate_statuses: dict[str, str]
    current_gate: str | None
    status: str = "running"
