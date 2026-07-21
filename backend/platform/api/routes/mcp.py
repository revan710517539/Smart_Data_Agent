from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import send_route_exception
from backend.platform.mcp import MCPToolCall
from backend.platform.runtime_config import cors_origin_for_request
from backend.platform.security import AuthenticationError, RateLimitExceeded


MCP_PROTOCOL_VERSION = "2025-11-25"
MCP_SUPPORTED_PROTOCOL_VERSIONS = {MCP_PROTOCOL_VERSION, "2025-06-18"}


def handle_mcp_servers_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        agent_id = str((params.get("agent_id") or [""])[0]).strip()
        servers = handler.services.mcp_gateway.list_servers_for_context(context.to_execution_context(), agent_id=agent_id)
        handler._send_json({"tenant_id": context.tenant_id, "servers": servers, "count": len(servers)})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_mcp_tools_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        agent_id = str((params.get("agent_id") or [""])[0]).strip()
        tools = handler.services.mcp_gateway.list_tools_for_context(context.to_execution_context(), agent_id=agent_id)
        handler._send_json({"tenant_id": context.tenant_id, "tools": tools, "count": len(tools)})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_mcp_call(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        server_id = str(payload.get("server_id") or "").strip()
        tool_name = str(payload.get("tool_name") or "").strip()
        arguments = payload.get("arguments") or {}
        agent_id = str(payload.get("agent_id") or "").strip()
        if not server_id or not tool_name:
            raise ValueError("server_id and tool_name are required.")
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object.")
        result = handler.services.mcp_gateway.call(
            MCPToolCall(
                server_id=server_id,
                tool_name=tool_name,
                context=context.to_execution_context(),
                arguments=arguments,
                agent_id=agent_id,
                approval_id=str(payload.get("approval_id") or "") or None,
            )
        )
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                "server_id": result.server_id,
                "tool_name": result.tool_name,
                "output": result.output,
            }
        )
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_mcp_stream_get(handler: Any, query: str) -> None:
    """Streamable HTTP endpoint without optional server-initiated SSE."""
    if not _mcp_origin_allowed(handler):
        _send_mcp_error(handler, None, -32001, "Origin is not allowed.", HTTPStatus.FORBIDDEN)
        return
    handler._send_json(
        {"error": "mcp_sse_not_supported", "message": "Use POST with application/json."},
        HTTPStatus.METHOD_NOT_ALLOWED,
        headers={"Allow": "POST"},
    )


def handle_mcp_stream_post(handler: Any) -> None:
    """MCP 2025-11-25 stateless Streamable HTTP JSON-RPC transport."""
    request_id: Any = None
    try:
        if not _mcp_origin_allowed(handler):
            _send_mcp_error(handler, None, -32001, "Origin is not allowed.", HTTPStatus.FORBIDDEN)
            return
        accept = str(handler.headers.get("Accept") or "").lower()
        if "application/json" not in accept or "text/event-stream" not in accept:
            _send_mcp_error(
                handler,
                None,
                -32600,
                "Accept must include application/json and text/event-stream.",
                HTTPStatus.NOT_ACCEPTABLE,
            )
            return
        payload = handler._read_json()
        if payload.get("jsonrpc") != "2.0" or not isinstance(payload.get("method"), str):
            _send_mcp_error(handler, payload.get("id"), -32600, "Invalid JSON-RPC request.", HTTPStatus.BAD_REQUEST)
            return
        request_id = payload.get("id")
        method = str(payload["method"])
        mirrored_method = str(handler.headers.get("Mcp-Method") or "").strip()
        if mirrored_method and mirrored_method != method:
            _send_mcp_error(handler, request_id, -32600, "Mcp-Method does not match the request.", HTTPStatus.BAD_REQUEST)
            return
        params = payload.get("params") or {}
        if not isinstance(params, dict):
            _send_mcp_error(handler, request_id, -32602, "Request params must be an object.", HTTPStatus.BAD_REQUEST)
            return
        context = handler._request_context(payload={})
        if method == "initialize":
            client_version = str(params.get("protocolVersion") or "")
            negotiated = client_version if client_version in MCP_SUPPORTED_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSION
            _send_mcp_result(
                handler,
                request_id,
                {
                    "protocolVersion": negotiated,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {
                        "name": "smart-data-agent",
                        "title": "Smart Data Agent governed MCP gateway",
                        "version": "0.1.0",
                    },
                    "instructions": "Tool calls are tenant scoped, permission checked, rate limited and may require four-eyes approval.",
                },
            )
            return
        protocol_version = str(handler.headers.get("MCP-Protocol-Version") or "").strip()
        if protocol_version not in MCP_SUPPORTED_PROTOCOL_VERSIONS:
            _send_mcp_error(handler, request_id, -32600, "Unsupported or missing MCP-Protocol-Version.", HTTPStatus.BAD_REQUEST)
            return
        if method.startswith("notifications/") or request_id is None:
            handler._send_empty(HTTPStatus.ACCEPTED)
            return
        if method == "ping":
            _send_mcp_result(handler, request_id, {})
            return
        if method == "tools/list":
            _handle_stream_tools_list(handler, request_id, context, params)
            return
        if method == "tools/call":
            _handle_stream_tool_call(handler, request_id, context, params)
            return
        _send_mcp_error(handler, request_id, -32601, "Method not found.", HTTPStatus.OK)
    except AuthenticationError:
        _send_mcp_error(handler, request_id, -32001, "Authentication required.", HTTPStatus.UNAUTHORIZED)
    except RateLimitExceeded as exc:
        _send_mcp_error(handler, request_id, -32002, "Rate limit exceeded.", HTTPStatus.TOO_MANY_REQUESTS)
    except Exception:
        _send_mcp_error(handler, request_id, -32603, "Internal MCP error.", HTTPStatus.OK)


def _handle_stream_tools_list(handler: Any, request_id: Any, context: Any, params: dict[str, Any]) -> None:
    tools = handler.services.mcp_gateway.list_tools_for_context(context.to_execution_context())
    try:
        offset = max(0, int(params.get("cursor") or 0))
    except (TypeError, ValueError):
        _send_mcp_error(handler, request_id, -32602, "Invalid tools cursor.", HTTPStatus.OK)
        return
    page_size = 100
    page = tools[offset : offset + page_size]
    result_tools = []
    for tool in page:
        definition = tool.get("tool_definition") if isinstance(tool.get("tool_definition"), dict) else {}
        result_tools.append(
            {
                "name": f"{tool['server_id']}.{tool['tool_name']}",
                "title": str(definition.get("title") or f"{tool['server_id']} {tool['tool_name']}"),
                "description": str(definition.get("description") or "Governed Smart Data Agent tool."),
                "inputSchema": definition.get("inputSchema")
                if isinstance(definition.get("inputSchema"), dict)
                else {"type": "object", "properties": {}},
                "annotations": {
                    "readOnlyHint": tool["tool_name"] in {"query", "schema", "search"},
                    "destructiveHint": False,
                    "openWorldHint": False,
                },
                "_meta": {
                    "io.smart-data-agent/allowed-agents": tool.get("allowed_agents", []),
                    "io.smart-data-agent/requires-approval": bool(tool.get("requires_approval")),
                    "io.smart-data-agent/risk-level": tool.get("risk_level"),
                },
            }
        )
    result: dict[str, Any] = {"tools": result_tools}
    if offset + page_size < len(tools):
        result["nextCursor"] = str(offset + page_size)
    _send_mcp_result(handler, request_id, result)


def _handle_stream_tool_call(handler: Any, request_id: Any, context: Any, params: dict[str, Any]) -> None:
    name = str(params.get("name") or "").strip()
    mirrored_name = str(handler.headers.get("Mcp-Name") or "").strip()
    if mirrored_name and mirrored_name != name:
        _send_mcp_error(handler, request_id, -32602, "Mcp-Name does not match the tool name.", HTTPStatus.OK)
        return
    server_id, separator, tool_name = name.partition(".")
    if not separator or not server_id or not tool_name:
        _send_mcp_error(handler, request_id, -32602, "Unknown tool.", HTTPStatus.OK)
        return
    known = any(
        item["server_id"] == server_id and item["tool_name"] == tool_name
        for item in handler.services.mcp_gateway.list_tools()
    )
    if not known:
        _send_mcp_error(handler, request_id, -32602, "Unknown tool.", HTTPStatus.OK)
        return
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        _send_mcp_error(handler, request_id, -32602, "Tool arguments must be an object.", HTTPStatus.OK)
        return
    metadata = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    agent_id = str(
        metadata.get("io.smart-data-agent/agent-id")
        or metadata.get("agent_id")
        or ""
    ).strip()
    approval_id = str(
        metadata.get("io.smart-data-agent/approval-id")
        or metadata.get("approval_id")
        or ""
    ).strip() or None
    try:
        output = handler.services.mcp_gateway.call(
            MCPToolCall(
                server_id=server_id,
                tool_name=tool_name,
                context=context.to_execution_context(),
                arguments=arguments,
                agent_id=agent_id,
                approval_id=approval_id,
            )
        ).output
    except (PermissionError, ValueError, RuntimeError, KeyError) as exc:
        error_code = (
            "permission_denied"
            if isinstance(exc, PermissionError)
            else "invalid_arguments"
            if isinstance(exc, ValueError)
            else "tool_unavailable"
            if isinstance(exc, KeyError)
            else "tool_execution_failed"
        )
        _send_mcp_result(
            handler,
            request_id,
            {
                "content": [{"type": "text", "text": error_code}],
                "isError": True,
                "_meta": {"io.smart-data-agent/error-code": error_code},
            },
        )
        return
    serialized = json.dumps(output, ensure_ascii=False, sort_keys=True)
    _send_mcp_result(
        handler,
        request_id,
        {
            "content": [{"type": "text", "text": serialized}],
            "structuredContent": output,
            "isError": False,
        },
    )


def _mcp_origin_allowed(handler: Any) -> bool:
    origin = handler.headers.get("Origin")
    return not origin or cors_origin_for_request(origin, handler.services.runtime_config) is not None


def _send_mcp_result(handler: Any, request_id: Any, result: dict[str, Any]) -> None:
    handler._send_json({"jsonrpc": "2.0", "id": request_id, "result": result})


def _send_mcp_error(
    handler: Any,
    request_id: Any,
    code: int,
    message: str,
    status: HTTPStatus,
) -> None:
    handler._send_json(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        status,
    )
