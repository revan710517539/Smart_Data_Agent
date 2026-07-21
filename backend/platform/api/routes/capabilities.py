from __future__ import annotations

from typing import Any

from backend.platform.api.support import send_route_exception


def handle_platform_capabilities_get(handler: Any, query: str) -> None:
    del query
    try:
        context = handler._request_context()
        agents = [
            {
                "agent_id": agent.agent_id,
                "name": agent.name,
                "type": agent.agent_type,
                "status": agent.status,
                "allowed_skills": list(agent.allowed_skills),
            }
            for agent in handler.services.agent_catalog.list_agents()
        ]
        groups = [
            {
                "group_id": group.group_id,
                "name": group.group_name,
                "controller_agent": group.controller_agent,
                "stage_gates": list(group.stage_gates),
                "agent_ids": [agent.agent_id for agent in group.agents],
            }
            for group in handler.services.agent_catalog.list_groups()
        ]
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                "agents": agents,
                "agent_groups": groups,
                "skills": handler.services.skill_registry.list_runtime_statuses(),
                "mcp_servers": handler.services.mcp_gateway.list_servers_for_context(context.to_execution_context()),
            }
        )
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)
