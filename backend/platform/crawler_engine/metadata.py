from __future__ import annotations

import json
from typing import Any

from .contracts import CrawlerOperation, CrawlerRequest
from .diagnostics import stable_json_hash
from .engine import CrawlerEngine


class TopicMetadataService:
    """SQL decomposition, raw-table projection, metadata artifacts and lineage."""

    def __init__(
        self,
        acquisition_store: Any,
        system_config_store: Any,
        object_store: Any,
        lineage_store: Any,
        crawler_engine: CrawlerEngine,
    ) -> None:
        self.store = acquisition_store
        self.system_config_store = system_config_store
        self.object_store = object_store
        self.lineage_store = lineage_store
        self.crawler_engine = crawler_engine

    def parse_sql(self, sql: str, dialect: str = "postgres") -> dict[str, Any]:
        return self.crawler_engine.sql_decomposer.parse(sql, dialect).to_dict()

    def refresh(
        self,
        tenant_id: str,
        topic_table_id: str,
        actor_user_id: str,
        *,
        connection_id: str | None = None,
        cascade: bool = False,
        dialect: str = "postgres",
    ) -> dict[str, Any]:
        topic = self.store.get_topic_definition(tenant_id, topic_table_id)
        decomposition = self.parse_sql(str(topic.get("sql") or ""), dialect)
        connection = self._connection(tenant_id, connection_id, topic)
        tables = _inferred_tables(decomposition)
        transport_status = "parsed_only"
        diagnostics: dict[str, Any] = {}
        provider_metadata: dict[str, Any] = {}
        if connection is not None:
            targets = tables if cascade else tables[:1]
            provider_tables: list[dict[str, Any]] = []
            diagnostic_runs: list[dict[str, Any]] = []
            statuses: list[str] = []
            for target in targets:
                qualified_name = str(target.get("qualified_name") or target.get("table") or "")
                result = self.crawler_engine.execute(
                    CrawlerRequest(
                        tenant_id=tenant_id,
                        operation_type=CrawlerOperation.METADATA_QUERY,
                        idempotency_key=(
                            f"metadata:{topic.get('code') or topic_table_id}:"
                            f"{decomposition['query_hash']}:{qualified_name}:{'cascade' if cascade else 'direct'}"
                        ),
                        connection=connection,
                        topic_table_id=str(topic.get("code") or topic_table_id),
                        readonly_sql=str(topic.get("sql") or ""),
                        parameters={"dialect": dialect, "cascade": cascade, "raw_table_name": qualified_name},
                        script=_metadata_script(connection, target, cascade),
                        timeout_seconds=240,
                    )
                )
                statuses.append(result.status)
                diagnostic_runs.append({"raw_table": qualified_name, **dict(result.diagnostics)})
                result_metadata = dict(result.metadata)
                if isinstance(result_metadata.get("tables"), list):
                    provider_tables.extend(item for item in result_metadata["tables"] if isinstance(item, dict))
                elif isinstance(result_metadata.get("fields"), list):
                    provider_tables.append({"qualified_name": qualified_name, "fields": result_metadata["fields"]})
            transport_status = (
                "succeeded" if statuses and all(item == "succeeded" for item in statuses)
                else "not_configured" if statuses and all(item == "not_configured" for item in statuses)
                else "partial"
            )
            diagnostics = {"runs": diagnostic_runs}
            provider_metadata = {"tables": provider_tables} if provider_tables else {}
            tables = _merge_provider_metadata(tables, provider_metadata)
            projection = self.store.upsert_topic_metadata(
                tenant_id,
                topic=topic,
                connection_id=str(connection["id"]),
                decomposition=decomposition,
                tables=tables,
                actor_user_id=actor_user_id,
            )
        else:
            projection = {
                "topic_table_id": topic_table_id,
                "table_count": len(tables),
                "schema_changed_tables": [],
                "synced_at": None,
            }
        artifact_payload = {
            "topic": {"id": topic.get("id"), "code": topic.get("code"), "name": topic.get("name")},
            "decomposition": decomposition,
            "tables": tables,
            "provider_metadata": provider_metadata,
            "transport_status": transport_status,
            "cascade": cascade,
        }
        stored = self.object_store.put(
            tenant_id,
            json.dumps(artifact_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"),
            ".json",
        )
        artifact = self.store.create_artifact(
            tenant_id,
            object_uri=stored.object_uri,
            content_hash=stored.content_hash,
            content_type="application/json; charset=utf-8",
            size_bytes=stored.size_bytes,
            status="active",
            created_by=actor_user_id,
            artifact_type="json",
        )
        for table in tables:
            self.lineage_store.record_edge(
                tenant_id,
                {
                    "source_type": "dataset",
                    "source_id": str(table["qualified_name"]),
                    "target_type": "topic_table",
                    "target_id": str(topic.get("code") or topic_table_id),
                    "edge_type": "reads",
                    "expression_hash": str(decomposition["query_hash"]),
                    "confidence": float(decomposition.get("confidence") or 1),
                    "metadata": {
                        "source_alias": table.get("alias"),
                        "metadata_artifact_id": artifact["artifact_id"],
                        "cascade": cascade,
                    },
                },
                actor_user_id,
            )
        provider_complete = bool(provider_metadata) and all(
            table.get("fields") and all(str(field.get("physical_type") or "") != "unknown" for field in table["fields"])
            for table in tables
        )
        status = "complete" if transport_status == "succeeded" and provider_complete else "partial" if tables else "failed"
        return {
            "topic_table_id": topic_table_id,
            "status": status,
            "transport_status": transport_status,
            "cascade": cascade,
            "decomposition": decomposition,
            "raw_tables": tables,
            "metadata_artifact_id": artifact["artifact_id"],
            "diagnostics": diagnostics,
            **projection,
        }

    def status(self, tenant_id: str, topic_table_id: str) -> dict[str, Any]:
        return self.store.metadata_status(tenant_id, topic_table_id)

    def executions(self, tenant_id: str, topic_table_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.list_execution_logs(tenant_id, topic_table_id, limit)

    def _connection(self, tenant_id: str, connection_id: str | None, topic: dict[str, Any]) -> dict[str, Any] | None:
        if connection_id:
            connection = self.system_config_store.get_data_connection(tenant_id, connection_id, reveal_secret=True)
            if connection is None:
                raise KeyError("data_connection_not_found")
            return connection
        connections = self.system_config_store.list_data_connections(tenant_id, reveal_secret=True)
        enabled = [item for item in connections if item.get("enabled") and not item.get("mockEnabled")]
        source = str(topic.get("source") or "").casefold()
        matched = [
            item for item in enabled
            if source and source in f"{item.get('sourceName', '')} {item.get('sourceType', '')}".casefold()
        ]
        verified = [item for item in matched or enabled if item.get("status") == "verified" and item.get("testStatus") == "verified"]
        if verified:
            return verified[0]
        # Stub mode may still persist SQL-inferred metadata without claiming that
        # the external platform was verified.
        if getattr(self.crawler_engine.transport, "name", "") == "stub" and enabled:
            return (matched or enabled)[0]
        return None


def _inferred_tables(decomposition: dict[str, Any]) -> list[dict[str, Any]]:
    raw_tables = [dict(item) for item in decomposition.get("raw_tables") or []]
    fields = [dict(item) for item in decomposition.get("fields") or []]
    result: list[dict[str, Any]] = []
    single_table = len(raw_tables) == 1
    for table in raw_tables:
        alias = str(table.get("alias") or table.get("table") or "")
        inferred: dict[str, dict[str, Any]] = {}
        for field in fields:
            for column in field.get("source_columns") or []:
                text = str(column)
                owner, _, name = text.partition(".")
                if not single_table and owner.casefold() not in {alias.casefold(), str(table.get("table") or "").casefold()}:
                    continue
                field_code = name if name else owner
                if field_code == "*":
                    continue
                inferred.setdefault(
                    field_code,
                    {
                        "field_code": field_code,
                        "field_name": field_code,
                        "physical_type": "unknown",
                        "is_nullable": True,
                        "is_dimension": not bool(field.get("aggregate")),
                        "is_measure": bool(field.get("aggregate")),
                        "metadata_source": "sql_inferred",
                    },
                )
        item = {**table, "fields": list(inferred.values())}
        item["schema_hash"] = stable_json_hash(item["fields"])
        result.append(item)
    return result


def _merge_provider_metadata(tables: list[dict[str, Any]], metadata: dict[str, Any]) -> list[dict[str, Any]]:
    provider_tables = metadata.get("tables") if isinstance(metadata.get("tables"), list) else []
    global_fields = metadata.get("fields") if isinstance(metadata.get("fields"), list) else []
    result: list[dict[str, Any]] = []
    for table in tables:
        match = next(
            (
                item for item in provider_tables
                if isinstance(item, dict)
                and str(item.get("qualified_name") or item.get("table") or "").casefold()
                in {str(table.get("qualified_name") or "").casefold(), str(table.get("table") or "").casefold()}
            ),
            None,
        )
        provider_fields = match.get("fields") if isinstance(match, dict) and isinstance(match.get("fields"), list) else global_fields
        if provider_fields:
            normalized = []
            for item in provider_fields:
                if not isinstance(item, dict):
                    continue
                code = str(item.get("field_code") or item.get("name") or item.get("字段名") or "").strip()
                if not code:
                    continue
                normalized.append(
                    {
                        "field_code": code,
                        "field_name": str(item.get("field_name") or item.get("comment") or item.get("注释") or code),
                        "physical_type": str(item.get("physical_type") or item.get("type") or item.get("类型") or "unknown"),
                        "is_nullable": str(item.get("nullable") or item.get("是否为空") or "true").lower() not in {"false", "否", "0"},
                        "comment": str(item.get("comment") or item.get("注释") or ""),
                        "business_description": str(item.get("business_description") or item.get("业务含义") or ""),
                        "sample_value_masked": str(item.get("sample_value_masked") or item.get("样例值") or ""),
                        "metadata_source": "provider",
                    }
                )
            next_table = {**table, "fields": normalized}
            next_table["schema_hash"] = stable_json_hash(normalized)
            result.append(next_table)
        else:
            result.append(table)
    return result


def _metadata_script(connection: dict[str, Any], table: dict[str, Any], cascade: bool) -> dict[str, Any]:
    config = connection.get("crawlerConfig") if isinstance(connection.get("crawlerConfig"), dict) else {}
    steps: list[dict[str, Any]] = [
        {"action": "goto", "url": "${login_url}", "timeout_ms": 20_000},
        {"action": "fill", "selector": str(config.get("accountSelector") or 'input[name="username"], input[name="account"]'), "value_key": "account", "timeout_ms": 10_000},
        {"action": "fill", "selector": str(config.get("passwordSelector") or 'input[type="password"]'), "value_key": "password", "timeout_ms": 10_000},
        {"action": "click", "selector": str(config.get("loginButtonSelector") or 'button[type="submit"]'), "timeout_ms": 10_000},
        {"action": "goto", "url": str(connection.get("metadataPageUrl") or "${query_page_url}"), "timeout_ms": 20_000},
    ]
    search_selector = str(config.get("metadataSearchSelector") or "").strip()
    row_selector = str(config.get("metadataRowSelector") or "").strip()
    column_selectors = config.get("metadataColumnSelectors")
    if search_selector and table:
        steps.append({"action": "search_table", "selector": search_selector, "value_key": "raw_table_name", "timeout_ms": 10_000})
    if row_selector and isinstance(column_selectors, dict):
        steps.append({"action": "extract_metadata", "selector": row_selector, "column_selectors": column_selectors, "timeout_ms": 20_000})
    return {"version": 1, "steps": steps, "metadata": {"profile": "metadata", "cascade": cascade}}
