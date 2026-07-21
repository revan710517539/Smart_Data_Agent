from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from backend.platform.tenancy import ExecutionContext


@dataclass(frozen=True)
class MCPServerSpec:
    server_id: str
    name: str
    server_type: str
    endpoint: str
    exposed_tools: tuple[str, ...]
    risk_level: str = "medium"
    status: str = "active"
    allowed_agents: tuple[str, ...] = ()
    tool_definitions: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPToolCall:
    server_id: str
    tool_name: str
    context: ExecutionContext
    arguments: dict[str, Any] = field(default_factory=dict)
    agent_id: str = ""
    approval_id: str | None = None


@dataclass(frozen=True)
class MCPToolResult:
    server_id: str
    tool_name: str
    output: dict[str, Any]


MCPToolHandler = Callable[[MCPToolCall], MCPToolResult]
