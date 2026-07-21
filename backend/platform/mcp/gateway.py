from __future__ import annotations

from backend.platform.governance import PermissionBroker, approval_input_hash
from backend.platform.observability import TraceRecorder
from backend.platform.tenancy import ExecutionContext

from .models import MCPServerSpec, MCPToolCall, MCPToolHandler, MCPToolResult


class MCPGateway:
    """Governed MCP boundary.

    MCP is treated as an external protocol. Agents should still call governed skills.
    """

    def __init__(
        self,
        permission_broker: PermissionBroker,
        trace_recorder: TraceRecorder,
        agent_catalog=None,
        approval_store=None,
    ) -> None:
        self.permission_broker = permission_broker
        self.trace_recorder = trace_recorder
        self.agent_catalog = agent_catalog
        self.approval_store = approval_store
        self._servers: dict[str, MCPServerSpec] = {}
        self._handlers: dict[tuple[str, str], MCPToolHandler] = {}

    def register_server(self, spec: MCPServerSpec, handlers: dict[str, MCPToolHandler]) -> None:
        self._servers[spec.server_id] = spec
        for tool_name in spec.exposed_tools:
            if tool_name not in handlers:
                raise ValueError(f"Missing MCP handler: {spec.server_id}.{tool_name}")
            self._handlers[(spec.server_id, tool_name)] = handlers[tool_name]

    def list_servers(self) -> list[dict]:
        return [
            {
                "server_id": spec.server_id,
                "name": spec.name,
                "server_type": spec.server_type,
                "endpoint": spec.endpoint,
                "exposed_tools": list(spec.exposed_tools),
                "risk_level": spec.risk_level,
                "requires_approval": spec.risk_level == "high",
                "status": spec.status,
                "allowed_agents": list(spec.allowed_agents),
            }
            for spec in sorted(self._servers.values(), key=lambda item: item.server_id)
        ]

    def list_servers_for_context(self, context: ExecutionContext, agent_id: str = "") -> list[dict]:
        visible_tools_by_server: dict[str, set[str]] = {}
        for tool in self.list_tools_for_context(context, agent_id=agent_id):
            visible_tools_by_server.setdefault(tool["server_id"], set()).add(tool["tool_name"])
        servers = []
        for server in self.list_servers():
            visible_tools = sorted(visible_tools_by_server.get(server["server_id"], set()))
            if not visible_tools:
                continue
            servers.append({**server, "exposed_tools": visible_tools})
        return servers

    def list_tools(self) -> list[dict]:
        return [
            {
                "server_id": spec.server_id,
                "tool_name": tool_name,
                "resource": f"mcp:{spec.server_id}.{tool_name}",
                "risk_level": spec.risk_level,
                "requires_approval": spec.risk_level == "high",
                "status": spec.status,
                "allowed_agents": list(spec.allowed_agents),
                "tool_definition": dict(spec.tool_definitions.get(tool_name) or {}),
            }
            for spec in sorted(self._servers.values(), key=lambda item: item.server_id)
            for tool_name in spec.exposed_tools
        ]

    def list_tools_for_context(self, context: ExecutionContext, agent_id: str = "") -> list[dict]:
        return [
            tool
            for tool in self.list_tools()
            if self.permission_broker.check_resource(context, str(tool["resource"]), "execute")
            and (not agent_id or agent_id in tool.get("allowed_agents", []))
        ]

    def call(self, call: MCPToolCall) -> MCPToolResult:
        spec = self._servers.get(call.server_id)
        if not spec or spec.status != "active":
            raise KeyError(f"Unknown or inactive MCP server: {call.server_id}")
        if call.tool_name not in spec.exposed_tools:
            raise KeyError(f"MCP tool not exposed: {call.server_id}.{call.tool_name}")
        if not call.agent_id:
            raise PermissionError("mcp_agent_identity_required")
        if self.agent_catalog is not None and not self.agent_catalog.has_agent(call.agent_id):
            raise PermissionError("mcp_agent_unknown")
        if spec.allowed_agents and call.agent_id not in spec.allowed_agents:
            raise PermissionError(f"mcp_agent_not_allowed:{call.agent_id}:{call.server_id}")
        _validate_tool_arguments(
            f"{call.server_id}.{call.tool_name}",
            call.arguments,
            spec.tool_definitions.get(call.tool_name, {}).get("inputSchema", {}),
        )
        self.permission_broker.require_resource(
            call.context,
            f"mcp:{call.server_id}.{call.tool_name}",
            "execute",
        )
        if spec.risk_level == "high":
            if not call.approval_id or self.approval_store is None:
                raise PermissionError(f"mcp_approval_required:{call.server_id}.{call.tool_name}")
            self.approval_store.consume(
                call.approval_id,
                tenant_id=call.context.tenant_id,
                requested_by=call.context.user_id,
                subject_type="mcp",
                subject_id=f"{call.server_id}.{call.tool_name}",
                action="execute",
                input_hash=approval_input_hash(call.arguments),
            )
        self.trace_recorder.add_span(
            "mcp.call",
            inputs={"server_id": call.server_id, "tool_name": call.tool_name, "agent_id": call.agent_id},
        )
        result = self._handlers[(call.server_id, call.tool_name)](call)
        return MCPToolResult(
            server_id=result.server_id,
            tool_name=result.tool_name,
            output=self._sanitize(result.output),
        )

    @staticmethod
    def _sanitize(output: dict) -> dict:
        return _sanitize_value(output)


def _sanitize_value(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if "password" in str(key).lower() or "secret" in str(key).lower() or "token" in str(key).lower():
                redacted[key] = "***"
            else:
                redacted[key] = _sanitize_value(item)
        return redacted
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    return value


def _validate_tool_arguments(tool_name: str, arguments: dict, schema: object) -> None:
    if not isinstance(arguments, dict):
        raise ValueError(f"mcp_tool_arguments_must_be_object:{tool_name}")
    if not isinstance(schema, dict):
        return
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    missing = [str(key) for key in required if str(key) not in arguments]
    if missing:
        raise ValueError(f"mcp_tool_missing_arguments:{tool_name}:{','.join(missing)}")
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    for key, value in arguments.items():
        definition = properties.get(key)
        if not isinstance(definition, dict):
            continue
        expected = str(definition.get("type") or "")
        valid = (
            not expected
            or (expected == "string" and isinstance(value, str))
            or (expected == "array" and isinstance(value, list))
            or (expected == "object" and isinstance(value, dict))
            or (expected == "integer" and isinstance(value, int) and not isinstance(value, bool))
            or (expected == "number" and isinstance(value, (int, float)) and not isinstance(value, bool))
            or (expected == "boolean" and isinstance(value, bool))
        )
        if not valid:
            raise ValueError(f"mcp_tool_argument_type_invalid:{tool_name}:{key}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in definition and value < definition["minimum"]:
                raise ValueError(f"mcp_tool_argument_below_minimum:{tool_name}:{key}")
            if "maximum" in definition and value > definition["maximum"]:
                raise ValueError(f"mcp_tool_argument_above_maximum:{tool_name}:{key}")
