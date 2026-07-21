from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.postgresql import PostgreSQLConnectionPool

from .store import _build_graph, _normalize_edge, _record_analysis_edges


class PostgreSQLLineageStore:
    def __init__(self, pool: PostgreSQLConnectionPool, *, owns_pool: bool = False) -> None:
        self.pool = pool
        self.owns_pool = owns_pool

    def close(self) -> None:
        if self.owns_pool:
            self.pool.close()

    def record_edge(self, tenant_id: str, edge: dict[str, Any], created_by: str = "") -> dict[str, Any]:
        normalized = _normalize_edge(tenant_id, edge, created_by)
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, created_by, required=False) if created_by else None
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_lineage_edges(
                        tenant_id, edge_key, source_type, source_id, target_type, target_id,
                        edge_type, expression_hash, confidence, metadata, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, NULLIF(%s, ''), %s, %s::jsonb, %s)
                    ON CONFLICT (tenant_id, source_type, source_id, target_type, target_id, edge_type)
                    DO UPDATE SET expression_hash = EXCLUDED.expression_hash,
                                  confidence = EXCLUDED.confidence,
                                  metadata = EXCLUDED.metadata,
                                  updated_at = now(), lock_version = platform_lineage_edges.lock_version + 1
                    """,
                    (
                        tenant_key, normalized["lineage_edge_id"], normalized["source_type"],
                        normalized["source_id"], normalized["target_type"], normalized["target_id"],
                        normalized["edge_type"], normalized["expression_hash"], normalized["confidence"],
                        json.dumps(normalized["metadata"], ensure_ascii=False, sort_keys=True), actor_key,
                    ),
                )
        return normalized

    def list_edges(self, tenant_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT e.edge_key, t.tenant_code, e.source_type, e.source_id,
                           e.target_type, e.target_id, e.edge_type, e.expression_hash,
                           e.confidence, e.metadata, u.external_subject AS created_by, e.created_at
                    FROM platform_lineage_edges e
                    JOIN platform_tenants t ON t.tenant_id = e.tenant_id
                    LEFT JOIN platform_user_profiles u ON u.user_id = e.created_by
                    WHERE e.tenant_id = %s
                    ORDER BY e.created_at, e.lineage_edge_id
                    """,
                    (tenant_key,),
                )
                rows = cursor.fetchall()
        return [self._from_row(row) for row in rows]

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

    @staticmethod
    def _from_row(row: Any) -> dict[str, Any]:
        metadata = _value(row, "metadata", 9) or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        created_at = _value(row, "created_at", 11)
        return {
            "lineage_edge_id": str(_value(row, "edge_key", 0)),
            "tenant_id": str(_value(row, "tenant_code", 1)),
            "source_type": str(_value(row, "source_type", 2)),
            "source_id": str(_value(row, "source_id", 3)),
            "target_type": str(_value(row, "target_type", 4)),
            "target_id": str(_value(row, "target_id", 5)),
            "edge_type": str(_value(row, "edge_type", 6)),
            "expression_hash": str(_value(row, "expression_hash", 7) or ""),
            "confidence": float(_value(row, "confidence", 8)),
            "metadata": dict(metadata),
            "created_by": str(_value(row, "created_by", 10) or ""),
            "created_at": created_at.isoformat() if isinstance(created_at, datetime) else str(created_at),
        }

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self.pool.connection() as connection:
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]
