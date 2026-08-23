from __future__ import annotations

from typing import Any

from backend.platform.mcp import MCPToolCall
from backend.platform.kernel.events import EventBus
from backend.platform.kernel.models import CapabilityPack
from backend.platform.skills import SkillRequest, SkillResult
from backend.platform.tenancy import ExecutionContext


class UnifiedExecutor:
    """Single execution entry. runtime_type dispatch; analysis never calls draft_provider."""

    def __init__(
        self,
        skill_executor: Any,
        mcp_gateway: Any | None = None,
        lineage_store: Any | None = None,
        knowledge_store: Any | None = None,
        memory_store: Any | None = None,
        model_gateway: Any | None = None,
        event_bus: EventBus | None = None,
        draft_provider: Any | None = None,
    ) -> None:
        self.skill_executor = skill_executor
        self.mcp_gateway = mcp_gateway
        self.lineage_store = lineage_store
        self.knowledge_store = knowledge_store
        self.memory_store = memory_store
        self.model_gateway = model_gateway
        self.event_bus = event_bus
        self.draft_provider = draft_provider

    def execute(
        self,
        context: ExecutionContext,
        capability_id: str,
        inputs: dict[str, Any],
        *,
        pack: CapabilityPack | None = None,
        agent_id: str = "",
        approval_id: str | None = None,
        allow_draft: bool = False,
    ) -> dict[str, Any]:
        entry = _pack_entry(pack, capability_id) if pack is not None else None
        runtime_type = str((entry or {}).get("runtime_type") or "python")
        kind = str((entry or {}).get("kind") or "executable")
        if runtime_type == "draft_provider" and not allow_draft:
            raise PermissionError("draft_provider_forbidden_on_analysis_path")
        if kind == "procedure":
            return {"capability_id": capability_id, "kind": "procedure", "output": {"applied": True, "trigger": (entry or {}).get("trigger") or {}}}
        if kind == "memory" or runtime_type == "context":
            return {"capability_id": capability_id, "kind": "memory", "output": {"applied": True}}
        self._emit("capability.pre-execute", context, {"capability_id": capability_id, "runtime_type": runtime_type})
        try:
            output = self._dispatch(context, capability_id, runtime_type, inputs, agent_id, approval_id)
            self._emit("capability.post-execute", context, {"capability_id": capability_id, "status": "ok"})
            return {"capability_id": capability_id, "kind": kind, "output": output}
        except Exception as exc:
            self._emit(
                "capability.post-execute",
                context,
                {"capability_id": capability_id, "status": "error", "error": type(exc).__name__},
            )
            raise

    def _dispatch(
        self,
        context: ExecutionContext,
        capability_id: str,
        runtime_type: str,
        inputs: dict[str, Any],
        agent_id: str,
        approval_id: str | None,
    ) -> dict[str, Any]:
        if runtime_type == "mcp" or capability_id.startswith("mcp:"):
            return self._call_mcp(context, capability_id, inputs, agent_id, approval_id)
        if runtime_type == "graph" or capability_id == "graph.query_metric_lineage":
            return self._call_graph(context, inputs)
        if runtime_type == "llm":
            if self.model_gateway is None:
                raise RuntimeError("model_gateway_unavailable")
            return self.model_gateway.complete(inputs)
        if runtime_type == "draft_provider":
            if self.draft_provider is None:
                raise RuntimeError("draft_provider_unavailable")
            return self.draft_provider.draft(inputs)
        if capability_id == "knowledge.search" and self.knowledge_store is not None:
            query = str(inputs.get("query") or inputs.get("question") or "")
            hits = self.knowledge_store.search(query, tenant_id=context.tenant_id)
            return {"hits": [_hit_payload(hit) for hit in hits]}
        if capability_id == "memory.search" and self.memory_store is not None:
            records = self.memory_store.search(context.tenant_id, statuses=("active",), limit=20)
            visible = [
                record
                for record in records
                if getattr(record, "subject_type", "tenant") != "user"
                or getattr(record, "subject_id", "") == context.user_id
            ]
            return {"memories": [getattr(record, "memory_id", "") for record in visible]}
        result = self.skill_executor.execute(
            SkillRequest(
                skill_id=capability_id,
                context=context,
                inputs=inputs,
                agent_id=agent_id or None,
                approval_id=approval_id,
            )
        )
        if isinstance(result, SkillResult):
            return dict(result.output)
        return dict(result)

    def _call_mcp(
        self,
        context: ExecutionContext,
        capability_id: str,
        inputs: dict[str, Any],
        agent_id: str,
        approval_id: str | None,
    ) -> dict[str, Any]:
        if self.mcp_gateway is None:
            raise RuntimeError("mcp_gateway_unavailable")
        raw = capability_id.removeprefix("mcp:")
        server_id, _, tool_name = raw.partition(".")
        result = self.mcp_gateway.call(
            MCPToolCall(
                server_id=str(inputs.get("server_id") or server_id),
                tool_name=str(inputs.get("tool_name") or tool_name),
                context=context,
                arguments=dict(inputs.get("arguments") or inputs),
                agent_id=agent_id,
                approval_id=approval_id,
            )
        )
        return dict(result.output)

    def _call_graph(self, context: ExecutionContext, inputs: dict[str, Any]) -> dict[str, Any]:
        if self.lineage_store is None or not hasattr(self.lineage_store, "graph"):
            raise RuntimeError("skill_unavailable:graph.query_metric_lineage:configured_unimplemented")
        return self.lineage_store.graph(
            context.tenant_id,
            str(inputs.get("entity_type") or "metric"),
            str(inputs.get("entity_id") or inputs.get("metric_id") or ""),
            direction=str(inputs.get("direction") or "both"),
            max_depth=int(inputs.get("max_depth") or 4),
        )

    def _emit(self, event_type: str, context: ExecutionContext, payload: dict[str, Any]) -> None:
        if self.event_bus is None:
            return
        self.event_bus.publish(
            event_type,
            {
                "tenant_id": context.tenant_id,
                "user_id": context.user_id,
                **payload,
            },
        )


def _pack_entry(pack: CapabilityPack, capability_id: str) -> dict[str, Any] | None:
    for entry in pack.entries:
        if str(entry.get("capability_id")) == capability_id:
            return dict(entry)
    return None


def _hit_payload(hit: Any) -> dict[str, Any]:
    document = getattr(hit, "document", None)
    return {
        "doc_id": getattr(document, "doc_id", ""),
        "title": getattr(document, "title", ""),
        "score": getattr(hit, "score", 0),
    }
