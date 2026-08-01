from __future__ import annotations

import re
from typing import Any


class CSVTopicMetadataService:
    """Deterministic topic-table metadata for the local CSV-only runtime.

    Topic tables remain saved data-application assets. Their SQL text can be
    inspected for documentation, but Smart Data Agent no longer opens a page,
    logs in, or calls an external metadata provider to refresh it.
    """

    def __init__(self, acquisition_store: Any, csv_source: Any) -> None:
        self.store = acquisition_store
        self.csv_source = csv_source

    def parse_sql(self, sql: str, dialect: str = "postgres") -> dict[str, Any]:
        normalized = " ".join(str(sql or "").split())
        tables = []
        for index, name in enumerate(re.findall(r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_.]*)", normalized, flags=re.IGNORECASE)):
            tables.append({"table": name, "qualified_name": name, "alias": name.rsplit(".", 1)[-1], "ordinal": index + 1})
        return {
            "dialect": dialect or "postgres",
            "query_hash": _stable_hash(normalized),
            "raw_tables": tables,
            "fields": [],
            "confidence": 1.0 if normalized else 0.0,
            "mode": "csv_folder",
        }

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
        csv_tables = self.csv_source.table_assets()
        return {
            "topic_table_id": topic_table_id,
            "status": "csv_catalog",
            "transport_status": "not_applicable",
            "cascade": cascade,
            "decomposition": decomposition,
            "raw_tables": [
                {
                    "qualified_name": table["tableNameEn"],
                    "display_name": table["tableNameCn"],
                    "relative_path": table.get("relativePath", ""),
                    "fields": [
                        {
                            "field_code": field["fieldNameEn"],
                            "field_name": field["fieldNameCn"],
                            "physical_type": field["type"],
                            "business_description": field["explanation"],
                        }
                        for field in table.get("fields", [])
                    ],
                }
                for table in csv_tables
            ],
            "metadata_artifact_id": "",
            "table_count": len(csv_tables),
            "schema_changed_tables": [],
            "synced_at": None,
            "message": "当前项目只读取 Origin_Data 文件夹中的 CSV；主题表元数据不再调用外部数据接入。",
        }

    def status(self, tenant_id: str, topic_table_id: str) -> dict[str, Any]:
        return {
            "topic_table_id": topic_table_id,
            "status": "csv_catalog",
            "source_mode": "csv_folder",
            "csv_file_count": len(self.csv_source.table_assets()),
        }

    def executions(self, tenant_id: str, topic_table_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        # Retain the UI contract while making clear there is no collection job.
        return []


def _stable_hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
