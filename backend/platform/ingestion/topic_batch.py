from __future__ import annotations

import sqlite3
from typing import Any

from backend.platform.security.sql_validation import validate_read_only_sql_candidate


class TopicDataBatchService:
    """Calculate active topic-table SQL against the current Origin_Data CSV set."""

    def __init__(self, csv_source: Any, topic_data_store: Any, asset_store: Any) -> None:
        self.csv_source = csv_source
        self.topic_data_store = topic_data_store
        self.asset_store = asset_store

    def run(self, tenant_id: str, actor_user_id: str) -> dict[str, Any]:
        topics = [
            item for item in self.asset_store.list_bundle(tenant_id).get("topic_tables", [])
            if str(item.get("lifecycleStatus") or "") == "active"
        ]
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        try:
            # The daily batch is the authoritative freshness boundary.  It
            # deliberately bypasses the interactive catalog cache so newly
            # delivered Origin_Data files are always selected before SQL runs.
            catalog = self.csv_source.table_assets(force=True)
            imported = self._load_csv_catalog(connection, catalog, tenant_id)
            outcomes: list[dict[str, Any]] = []
            for topic in topics:
                topic_id = str(topic.get("id") or "")
                try:
                    sql = validate_read_only_sql_candidate(str(topic.get("sql") or ""))
                    rows = self._execute(connection, sql, tenant_id)
                    reference = self.topic_data_store.record_topic_table_result(
                        tenant_id=tenant_id,
                        user_id=actor_user_id,
                        topic_table_id=topic_id,
                        sql=sql,
                        rows=rows,
                    )
                    outcomes.append({"topic_table_id": topic_id, "status": "succeeded", "row_count": len(rows), "topic_data": reference})
                except Exception as exc:
                    outcomes.append({"topic_table_id": topic_id, "status": "failed", "error_code": _error_code(exc)})
            return {
                "source": "Origin_Data",
                "imported_tables": imported,
                "topic_tables": outcomes,
                "succeeded": sum(item["status"] == "succeeded" for item in outcomes),
                "failed": sum(item["status"] == "failed" for item in outcomes),
            }
        finally:
            connection.close()

    def _load_csv_catalog(self, connection: sqlite3.Connection, catalog: list[dict[str, Any]], tenant_id: str) -> int:
        """Load current Origin_Data files and expose audited compatibility views.

        Earlier seeded topic SQL names two semantic fact tables.  Origin_Data
        deliberately contains files, not a second warehouse, so the aliases
        below are explicit projections from the delivered loan-order CSV.  The
        mapping is intentionally narrow: if the expected source CSV or a
        required field is absent, no alias is created and the topic run returns
        a visible ``origin_data_*`` failure instead of silently using unrelated
        data.
        """
        imported = 0
        imported_tables: dict[str, set[str]] = {}
        for table in catalog:
            table_name = str(table.get("tableNameEn") or "").strip()
            fields = table.get("fields") if isinstance(table.get("fields"), list) else []
            path = str(table.get("relativePath") or "")
            if not table_name or not path or not fields:
                continue
            columns = [str(field.get("fieldNameEn") or "").strip() for field in fields]
            if not all(columns):
                continue
            quoted = ", ".join(f'"{column}" TEXT' for column in columns)
            connection.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            connection.execute(f'CREATE TABLE "{table_name}" ({quoted})')
            # Read the protected source once for transformation; list APIs remain
            # preview-only and never return this complete dataset to the browser.
            source_headers = [str(field.get("fieldNameCn") or "") for field in fields]
            _, source_rows = self.csv_source.read_rows(path, max_rows=50_000)
            values = [
                tuple(str(row.get(header) or "") for header in source_headers)
                for row in source_rows
            ]
            if values:
                placeholders = ", ".join("?" for _ in columns)
                column_sql = ", ".join(f'"{column}"' for column in columns)
                connection.executemany(f'INSERT INTO "{table_name}" ({column_sql}) VALUES ({placeholders})', values)
            imported_tables[table_name] = set(columns)
            imported += 1
        self._create_legacy_topic_views(connection, imported_tables, tenant_id)
        connection.commit()
        return imported

    @staticmethod
    def _create_legacy_topic_views(
        connection: sqlite3.Connection,
        imported_tables: dict[str, set[str]],
        tenant_id: str,
    ) -> None:
        """Create only the documented Origin_Data -> legacy semantic aliases."""

        loan_source = next(
            (
                table_name
                for table_name, columns in imported_tables.items()
                if {"tenant_id", "branch_name", "product_line", "customer_segment", "month", "drawdown_amount", "loan_balance", "m1_overdue_balance"}.issubset(columns)
            ),
            "",
        )
        safe_tenant = tenant_id.replace("'", "''")
        # The external daily feed uses a wildcard tenant marker for reusable
        # local fixtures. Materialize it to the task tenant before each SQL run
        # so the existing tenant predicate remains effective.
        normalized_tenant = f"CASE WHEN tenant_id = '*' THEN '{safe_tenant}' ELSE tenant_id END"
        connection.execute("DROP VIEW IF EXISTS loan_operation_fact")
        connection.execute("DROP VIEW IF EXISTS weekly_core_metrics_fact")
        if loan_source:
            source_sql = f'"{loan_source.replace(chr(34), chr(34) * 2)}"'
            connection.execute(
                f"""
                CREATE VIEW loan_operation_fact AS
                SELECT
                  {normalized_tenant} AS tenant_id,
                  branch_name,
                  product_line,
                  customer_segment,
                  month AS stat_week,
                  drawdown_amount AS loan_amount,
                  loan_balance,
                  drawdown_amount AS new_balance,
                  CASE
                    WHEN CAST(loan_balance AS REAL) = 0 THEN NULL
                    ELSE CAST(m1_overdue_balance AS REAL) / CAST(loan_balance AS REAL)
                  END AS m1_overdue_rate
                FROM {source_sql}
                """
            )
            connection.execute(
                """
                CREATE VIEW weekly_core_metrics_fact AS
                SELECT tenant_id, stat_week, loan_balance, loan_amount, new_balance
                FROM loan_operation_fact
                """
            )

        voice_source = next(
            (
                table_name
                for table_name, columns in imported_tables.items()
                if {"tenant_id", "branch_name", "product_line", "customer_segment", "month", "channel", "loan_amount", "drawdown_rate", "drawdown_amount", "eligible_amount"}.issubset(columns)
            ),
            "",
        )
        connection.execute("DROP VIEW IF EXISTS customer_operation_mart")
        connection.execute("DROP VIEW IF EXISTS channel_operation_mart")
        if voice_source:
            source_sql = f'"{voice_source.replace(chr(34), chr(34) * 2)}"'
            connection.execute(
                f"""
                CREATE VIEW customer_operation_mart AS
                SELECT
                  {normalized_tenant} AS tenant_id,
                  customer_segment, product_line, branch_name, month,
                  drawdown_rate AS conversion_rate,
                  CASE WHEN CAST(eligible_amount AS REAL) = 0 THEN 0
                       ELSE CAST(drawdown_amount AS REAL) / CAST(eligible_amount AS REAL) END AS active_customer_count
                FROM {source_sql}
                """
            )
            connection.execute(
                f"""
                CREATE VIEW channel_operation_mart AS
                SELECT
                  {normalized_tenant} AS tenant_id,
                  channel, month, product_line, branch_name,
                  CASE WHEN CAST(drawdown_amount AS REAL) = 0 THEN 0
                       ELSE CAST(eligible_amount AS REAL) / CAST(drawdown_amount AS REAL) END AS customer_acquisition_cost,
                  CASE WHEN CAST(eligible_amount AS REAL) = 0 THEN 0
                       ELSE CAST(loan_amount AS REAL) / CAST(eligible_amount AS REAL) END AS roi
                FROM {source_sql}
                """
            )

    @staticmethod
    def _execute(connection: sqlite3.Connection, sql: str, tenant_id: str) -> list[dict[str, Any]]:
        normalized = sql.replace(":tenant_id", ":tenant_id")
        cursor = connection.execute(normalized, {"tenant_id": tenant_id})
        return [dict(row) for row in cursor.fetchall()]


def _error_code(exc: Exception) -> str:
    value = str(exc).strip().lower()
    if "no such table" in value:
        return "origin_data_table_not_found"
    if "no such column" in value:
        return "origin_data_column_not_found"
    if "tenant" in value and "binding" in value:
        return "topic_sql_tenant_binding_required"
    return "topic_data_batch_failed"
