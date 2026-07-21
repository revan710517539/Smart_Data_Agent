from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.platform.semantic import SemanticQueryRequest, SemanticQueryService

from .gateway import MCPGateway
from .models import MCPServerSpec, MCPToolCall, MCPToolResult


def load_mcp_server_specs(config_dir: str | Path = "configs/mcp_servers") -> list[MCPServerSpec]:
    root = Path(config_dir)
    specs: list[MCPServerSpec] = []
    for path in sorted(root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        specs.append(
            MCPServerSpec(
                server_id=str(payload["server_id"]),
                name=str(payload.get("server_name") or payload.get("name") or payload["server_id"]),
                server_type=str(payload.get("server_type") or "generic"),
                endpoint=str(payload.get("endpoint") or f"mcp://{payload['server_id']}"),
                exposed_tools=tuple(str(tool) for tool in payload.get("exposed_tools", [])),
                risk_level=str(payload.get("risk_level") or "medium"),
                status=str(payload.get("status") or "active"),
                allowed_agents=tuple(str(agent) for agent in payload.get("allowed_agents", [])),
                tool_definitions={
                    str(tool_name): dict(definition)
                    for tool_name, definition in dict(payload.get("tool_definitions") or {}).items()
                    if isinstance(definition, dict)
                },
            )
        )
    return specs


def register_local_mcp_handlers(
    gateway: MCPGateway,
    knowledge_store: Any,
    semantic_service: SemanticQueryService,
    config_dir: str | Path = "configs/mcp_servers",
) -> None:
    for spec in load_mcp_server_specs(config_dir):
        if spec.server_id == "database":
            gateway.register_server(spec, _database_handlers(semantic_service))
        elif spec.server_id == "knowledge":
            gateway.register_server(spec, _knowledge_handlers(knowledge_store))
        else:
            raise ValueError(f"No production MCP transport/handler registered for server: {spec.server_id}")


def _database_handlers(semantic_service: SemanticQueryService) -> dict[str, Any]:
    def query(call: MCPToolCall) -> MCPToolResult:
        dataset_id = str(call.arguments.get("dataset_id") or "loan_operation_mart")
        metrics_value = call.arguments.get("metrics") or [call.arguments.get("metric") or "loan_amount"]
        dimensions_value = call.arguments.get("dimensions") or [call.arguments.get("dimension") or "branch_name"]
        metrics = tuple(str(item) for item in metrics_value if str(item or "").strip())
        dimensions = tuple(str(item) for item in dimensions_value if str(item or "").strip())
        filters = call.arguments.get("filters") if isinstance(call.arguments.get("filters"), dict) else {}
        result = semantic_service.query(SemanticQueryRequest(
            question=str(call.arguments.get("question") or "MCP governed query"),
            tenant_id=call.context.tenant_id,
            user_id=call.context.user_id,
            dataset_id=dataset_id,
            metrics=metrics,
            dimensions=dimensions,
            filters=filters,
            limit=int(call.arguments.get("limit") or 20),
            context={"mcp_server_id": call.server_id, "mcp_tool_name": call.tool_name},
        ))
        return MCPToolResult(
            server_id=call.server_id,
            tool_name=call.tool_name,
            output={
                "dataset_id": str(result.semantic_info.get("dataset_id") or dataset_id),
                "metrics": list(metrics),
                "dimensions": list(dimensions),
                "rows": result.data,
                "sql": result.sql,
                "parameters": result.parameters,
                "semantic_info": result.semantic_info,
            },
        )

    def schema(call: MCPToolCall) -> MCPToolResult:
        client = getattr(semantic_service, "client", None)
        fallback = getattr(client, "fallback", client)
        warehouse = getattr(fallback, "warehouse", None)
        datasets = warehouse.list_datasets() if warehouse and hasattr(warehouse, "list_datasets") else []
        return MCPToolResult(
            server_id=call.server_id,
            tool_name=call.tool_name,
            output={"datasets": datasets, "source": "authorized_semantic_runtime"},
        )

    return {"query": query, "schema": schema}


def _knowledge_handlers(knowledge_store: Any) -> dict[str, Any]:
    def search(call: MCPToolCall) -> MCPToolResult:
        query_text = str(call.arguments.get("query") or call.arguments.get("q") or "")
        hits = knowledge_store.search(query_text, tenant_id=call.context.tenant_id, limit=int(call.arguments.get("limit") or 5))
        return MCPToolResult(
            server_id=call.server_id,
            tool_name=call.tool_name,
            output={
                "hits": [
                    {
                        "doc_id": hit.document.doc_id,
                        "title": hit.document.title,
                        "content": hit.document.content,
                        "score": hit.score,
                        "matched_terms": list(hit.matched_terms),
                        "chunk_id": hit.chunk_id,
                        "knowledge_version_id": hit.knowledge_version_id,
                        "locator": hit.locator,
                    }
                    for hit in hits
                ]
            },
        )

    def ingest(call: MCPToolCall) -> MCPToolResult:
        title = str(call.arguments.get("title") or "").strip()
        content = str(call.arguments.get("content") or "").strip()
        if not title or not content:
            raise ValueError("title and content are required.")
        create_document = getattr(knowledge_store, "create_document", None)
        if not callable(create_document):
            raise RuntimeError("governed_knowledge_ingestion_unavailable")
        doc = create_document(
            call.context.tenant_id,
            {
                "document_id": str(call.arguments.get("doc_id") or f"kd_{uuid4().hex[:12]}"),
                "title": title,
                "content": content,
                "document_type": str(call.arguments.get("document_type") or "other"),
                "domains": [str(item) for item in call.arguments.get("domains", []) if item],
                "tags": [str(item) for item in call.arguments.get("tags", []) if item],
            },
            call.context.user_id,
        )
        return MCPToolResult(
            server_id=call.server_id,
            tool_name=call.tool_name,
            output={
                "doc_id": doc["document_id"],
                "title": doc["title"],
                "tenant_id": doc["tenant_id"],
                "status": doc["status"],
                "publishable": False,
                "message": "Knowledge was staged for review and is not searchable until approved.",
            },
        )

    return {"search": search, "ingest": ingest}
