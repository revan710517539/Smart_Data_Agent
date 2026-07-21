from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4


TaskType = Literal["simple_metric_query", "diagnostic_analysis", "knowledge_qa", "report_generation"]


@dataclass(frozen=True)
class AgentStep:
    agent: str
    action: str
    output: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisTask:
    question: str
    task_type: TaskType
    tenant_id: str
    user_id: str
    task_id: str = field(default_factory=lambda: f"task_{uuid4().hex[:12]}")
    request_id: str = field(default_factory=lambda: f"req_{uuid4().hex[:16]}")
    execution_id: str = ""
    revision: int = 1
    parent_execution_id: str | None = None
    execution_mode: str = "mock"
    status: str = "planning"
    plan: list[AgentStep] = field(default_factory=list)
    analysis_plan: dict[str, Any] = field(default_factory=dict)
    skill_results: list[dict[str, Any]] = field(default_factory=list)
    knowledge_refs: list[dict[str, Any]] = field(default_factory=list)
    conclusions: list[str] = field(default_factory=list)
    review: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    manual_edits: dict[str, Any] = field(default_factory=dict)
    agent_group_state: dict[str, Any] = field(default_factory=dict)
    agent_group_run: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.execution_id:
            self.execution_id = self.task_id
