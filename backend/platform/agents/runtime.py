from __future__ import annotations

from typing import Any

from backend.platform.observability import TraceRecorder
from backend.platform.skills import SkillExecutor, SkillRequest, SkillResult

from .catalog import AgentCatalog
from .models import AgentGroupRun


class AgentRuntime:
    """Enforce Agent identity, allowed skills and ordered stage gates."""

    def __init__(self, catalog: AgentCatalog, skill_executor: SkillExecutor, trace_recorder: TraceRecorder) -> None:
        self.catalog = catalog
        self.skill_executor = skill_executor
        self.trace_recorder = trace_recorder

    def begin_group(self, group_id: str) -> AgentGroupRun:
        group = self.catalog.get_group(group_id)
        gates = {gate: "pending" for gate in group.stage_gates}
        return AgentGroupRun(
            group_id=group_id,
            gate_statuses=gates,
            current_gate=group.stage_gates[0] if group.stage_gates else None,
        )

    def require_operation(self, agent_id: str, operation_id: str) -> None:
        agent = self.catalog.get_agent(agent_id)
        if agent.status != "active":
            raise PermissionError(f"agent_inactive:{agent_id}")
        if operation_id not in agent.allowed_skills:
            raise PermissionError(f"agent_skill_not_allowed:{agent_id}:{operation_id}")
        self.trace_recorder.add_span(
            "agent.operation.authorized",
            inputs={"agent_id": agent_id, "operation_id": operation_id},
        )

    def execute_skill(self, agent_id: str, request: SkillRequest) -> SkillResult:
        self.require_operation(agent_id, request.skill_id)
        governed_request = SkillRequest(
            skill_id=request.skill_id,
            context=request.context,
            inputs=request.inputs,
            trace_id=request.trace_id,
            agent_id=agent_id,
            approval_id=request.approval_id,
        )
        return self.skill_executor.execute(governed_request)

    def complete_gate(self, run: AgentGroupRun, gate: str, passed: bool, evidence: dict[str, Any] | None = None) -> None:
        group = self.catalog.get_group(run.group_id)
        if gate not in run.gate_statuses:
            raise KeyError(f"unknown_agent_gate:{run.group_id}:{gate}")
        expected = next((name for name in group.stage_gates if run.gate_statuses[name] == "pending"), None)
        if expected != gate:
            raise RuntimeError(f"agent_gate_out_of_order:expected={expected}:received={gate}")
        run.gate_statuses[gate] = "passed" if passed else "failed"
        self.trace_recorder.add_span(
            "agent.stage_gate",
            inputs={"group_id": run.group_id, "gate": gate},
            outputs={"passed": passed, "evidence": evidence or {}},
            status="ok" if passed else "error",
        )
        if not passed:
            run.status = "blocked"
            run.current_gate = gate
            return
        run.current_gate = next((name for name in group.stage_gates if run.gate_statuses[name] == "pending"), None)
        if run.current_gate is None:
            run.status = "completed"

    @staticmethod
    def snapshot(run: AgentGroupRun) -> dict[str, Any]:
        return {
            "group_id": run.group_id,
            "gate_statuses": dict(run.gate_statuses),
            "current_gate": run.current_gate,
            "status": run.status,
        }
