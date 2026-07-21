from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import deque
from pathlib import Path
from typing import Any

from backend.platform.storage import connect_sqlite


EDGE_TYPES = {"reads", "derives", "aggregates", "references", "publishes", "generates"}


class InMemoryLineageStore:
    def __init__(self) -> None:
        self._edges: dict[str, dict[str, Any]] = {}

    def close(self) -> None:
        return None

    def record_edge(self, tenant_id: str, edge: dict[str, Any], created_by: str = "") -> dict[str, Any]:
        normalized = _normalize_edge(tenant_id, edge, created_by)
        self._edges[normalized["lineage_edge_id"]] = normalized
        return dict(normalized)

    def list_edges(self, tenant_id: str) -> list[dict[str, Any]]:
        return [dict(edge) for edge in self._edges.values() if edge["tenant_id"] == tenant_id]

    def graph(
        self,
        tenant_id: str,
        entity_type: str,
        entity_id: str,
        *,
        direction: str = "both",
        max_depth: int = 4,
    ) -> dict[str, Any]:
        return _build_graph(self.list_edges(tenant_id), entity_type, entity_id, direction, max_depth)

    def record_analysis(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return _record_analysis_edges(self, payload)


class SQLiteLineageStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._conn = connect_sqlite(self.db_path)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def record_edge(self, tenant_id: str, edge: dict[str, Any], created_by: str = "") -> dict[str, Any]:
        normalized = _normalize_edge(tenant_id, edge, created_by)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_lineage_edges(
                    lineage_edge_id, tenant_id, source_type, source_id,
                    target_type, target_id, edge_type, expression_hash,
                    confidence, metadata, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, source_type, source_id, target_type, target_id, edge_type)
                DO UPDATE SET
                    expression_hash = excluded.expression_hash,
                    confidence = excluded.confidence,
                    metadata = excluded.metadata,
                    created_by = excluded.created_by
                """,
                (
                    normalized["lineage_edge_id"],
                    tenant_id,
                    normalized["source_type"],
                    normalized["source_id"],
                    normalized["target_type"],
                    normalized["target_id"],
                    normalized["edge_type"],
                    normalized["expression_hash"],
                    normalized["confidence"],
                    json.dumps(normalized["metadata"], ensure_ascii=False, sort_keys=True),
                    normalized["created_by"],
                ),
            )
        return normalized

    def list_edges(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT * FROM platform_lineage_edges
            WHERE tenant_id = ? ORDER BY created_at, lineage_edge_id
            """,
            (tenant_id,),
        ).fetchall()
        return [
            {
                **dict(row),
                "metadata": json.loads(row["metadata"] or "{}"),
            }
            for row in rows
        ]

    def graph(
        self,
        tenant_id: str,
        entity_type: str,
        entity_id: str,
        *,
        direction: str = "both",
        max_depth: int = 4,
    ) -> dict[str, Any]:
        return _build_graph(self.list_edges(tenant_id), entity_type, entity_id, direction, max_depth)

    def record_analysis(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return _record_analysis_edges(self, payload)


def _record_analysis_edges(store: Any, payload: dict[str, Any]) -> list[dict[str, Any]]:
    tenant_id = str(payload.get("tenant_id") or "")
    task_id = str(payload.get("task_id") or "")
    execution_id = str(payload.get("execution_id") or task_id)
    user_id = str(payload.get("user_id") or "")
    if not tenant_id or not task_id:
        raise ValueError("lineage_analysis_identity_required")
    plan = payload.get("analysis_plan") if isinstance(payload.get("analysis_plan"), dict) else {}
    results = payload.get("skill_results") if isinstance(payload.get("skill_results"), list) else []
    result = results[0] if results and isinstance(results[0], dict) else {}
    evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
    dataset_id = str(plan.get("dataset_id") or evidence.get("dataset_id") or "")
    query_id = f"{task_id}:query:{payload.get('revision') or 1}"
    evidence_id = str(evidence.get("evidence_id") or "")
    expression_hash = str(evidence.get("executed_sql_sha256") or "")
    edges: list[dict[str, Any]] = []
    if dataset_id:
        edges.append(
            store.record_edge(
                tenant_id,
                {
                    "source_type": "dataset",
                    "source_id": dataset_id,
                    "target_type": "analysis_query",
                    "target_id": query_id,
                    "edge_type": "reads",
                    "expression_hash": expression_hash,
                    "metadata": {"execution_id": execution_id},
                },
                user_id,
            )
        )
    for definition in plan.get("metric_definitions", []):
        if not isinstance(definition, dict):
            continue
        metric_code = str(definition.get("metric_code") or "")
        version = str(definition.get("version") or "")
        if not metric_code or not version:
            continue
        edges.append(
            store.record_edge(
                tenant_id,
                {
                    "source_type": "metric_version",
                    "source_id": f"{dataset_id}:{metric_code}:{version}",
                    "target_type": "analysis_query",
                    "target_id": query_id,
                    "edge_type": "aggregates",
                    "expression_hash": expression_hash,
                    "metadata": {
                        "metric_code": metric_code,
                        "aggregation": definition.get("aggregation"),
                        "numerator": definition.get("numerator"),
                        "denominator": definition.get("denominator"),
                    },
                },
                user_id,
            )
        )
    if evidence_id:
        edges.append(
            store.record_edge(
                tenant_id,
                {
                    "source_type": "analysis_query",
                    "source_id": query_id,
                    "target_type": "analysis_evidence",
                    "target_id": evidence_id,
                    "edge_type": "generates",
                    "expression_hash": expression_hash,
                },
                user_id,
            )
        )
        edges.append(
            store.record_edge(
                tenant_id,
                {
                    "source_type": "analysis_evidence",
                    "source_id": evidence_id,
                    "target_type": "analysis_task",
                    "target_id": task_id,
                    "edge_type": "derives",
                    "metadata": {"execution_id": execution_id},
                },
                user_id,
            )
        )
    for knowledge_ref in payload.get("knowledge_refs", []):
        if not isinstance(knowledge_ref, dict):
            continue
        source_id = str(knowledge_ref.get("chunk_id") or knowledge_ref.get("doc_id") or "")
        if source_id:
            edges.append(
                store.record_edge(
                    tenant_id,
                    {
                        "source_type": "knowledge_chunk",
                        "source_id": source_id,
                        "target_type": "analysis_task",
                        "target_id": task_id,
                        "edge_type": "references",
                        "metadata": {"citation_id": knowledge_ref.get("citation_id")},
                    },
                    user_id,
                )
            )
    return edges


def _normalize_edge(tenant_id: str, edge: dict[str, Any], created_by: str) -> dict[str, Any]:
    values = {
        key: str(edge.get(key) or "").strip()
        for key in ("source_type", "source_id", "target_type", "target_id", "edge_type")
    }
    if not tenant_id or any(not value for value in values.values()):
        raise ValueError("lineage_edge_identity_required")
    if values["edge_type"] not in EDGE_TYPES:
        raise ValueError("lineage_edge_type_invalid")
    expression_hash = str(edge.get("expression_hash") or "").strip()
    if expression_hash and (len(expression_hash) != 64 or any(char not in "0123456789abcdef" for char in expression_hash.lower())):
        raise ValueError("lineage_expression_hash_invalid")
    confidence = float(edge.get("confidence", 1))
    if not 0 <= confidence <= 1:
        raise ValueError("lineage_confidence_invalid")
    identity = "|".join((tenant_id, *values.values()))
    return {
        "lineage_edge_id": "lin_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
        "tenant_id": tenant_id,
        **values,
        "expression_hash": expression_hash.lower(),
        "confidence": confidence,
        "metadata": _safe_metadata(edge.get("metadata")),
        "created_by": created_by,
    }


def _safe_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, item in value.items():
        if len(safe) >= 20:
            break
        key_text = str(key)[:80]
        if isinstance(item, (str, int, float, bool)) or item is None:
            safe[key_text] = item if not isinstance(item, str) else item[:500]
    return safe


def _build_graph(
    edges: list[dict[str, Any]],
    entity_type: str,
    entity_id: str,
    direction: str,
    max_depth: int,
) -> dict[str, Any]:
    if direction not in {"upstream", "downstream", "both"}:
        raise ValueError("lineage_direction_invalid")
    bounded_depth = max(0, min(int(max_depth), 8))
    root = (str(entity_type).strip(), str(entity_id).strip())
    if not all(root):
        raise ValueError("lineage_root_required")
    queue = deque([(root, 0)])
    visited = {root}
    selected: dict[str, dict[str, Any]] = {}
    while queue:
        node, depth = queue.popleft()
        if depth >= bounded_depth:
            continue
        for edge in edges:
            source = (str(edge["source_type"]), str(edge["source_id"]))
            target = (str(edge["target_type"]), str(edge["target_id"]))
            neighbor = None
            if direction in {"downstream", "both"} and source == node:
                neighbor = target
            elif direction in {"upstream", "both"} and target == node:
                neighbor = source
            if neighbor is None:
                continue
            selected[str(edge["lineage_edge_id"])] = edge
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))
    nodes = [
        {"entity_type": node_type, "entity_id": node_id, "is_root": (node_type, node_id) == root}
        for node_type, node_id in sorted(visited)
    ]
    return {
        "root": {"entity_type": root[0], "entity_id": root[1]},
        "direction": direction,
        "max_depth": bounded_depth,
        "nodes": nodes,
        "edges": list(selected.values()),
    }
