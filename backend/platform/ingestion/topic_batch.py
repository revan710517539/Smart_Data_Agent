from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

try:
    import polars as pl
except ImportError:  # Keep control-plane startup independent from optional batch execution.
    pl = None  # type: ignore[assignment]

from backend.platform.security.sql_validation import validate_read_only_sql_candidate


class TopicDataBatchService:
    """Calculate active topic-table SQL against the current Origin_Data CSV set."""

    def __init__(self, csv_source: Any, topic_data_store: Any, asset_store: Any) -> None:
        self.csv_source = csv_source
        self.topic_data_store = topic_data_store
        self.asset_store = asset_store

    def run(self, tenant_id: str, actor_user_id: str) -> dict[str, Any]:
        if pl is None:
            raise RuntimeError("polars_runtime_required")
        topics = [
            item for item in self.asset_store.list_bundle(tenant_id).get("topic_tables", [])
            if str(item.get("lifecycleStatus") or "") == "active"
        ]
        # The daily batch deliberately bypasses the interactive catalog cache,
        # so newly delivered files become one immutable calculation boundary.
        tenant_source = self.csv_source.for_tenant(tenant_id)
        catalog = tenant_source.table_assets(force=True)
        if not catalog:
            raise RuntimeError("tenant_raw_source_files_missing")
        frames = self._load_csv_catalog(catalog, tenant_id, tenant_source)
        outcomes: list[dict[str, Any]] = []
        for topic in topics:
            topic_id = str(topic.get("id") or "")
            try:
                sql = validate_read_only_sql_candidate(str(topic.get("sql") or ""))
                rows = self._execute(frames, sql, tenant_id)
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
            "execution_engine": "polars_lazy_csv",
            "imported_tables": len(frames),
            "topic_tables": outcomes,
            "succeeded": sum(item["status"] == "succeeded" for item in outcomes),
            "failed": sum(item["status"] == "failed" for item in outcomes),
        }

    def _load_csv_catalog(self, catalog: list[dict[str, Any]], tenant_id: str, tenant_source: Any) -> dict[str, pl.LazyFrame]:
        """Register lazy CSV scans and audited compatibility projections.

        Earlier seeded topic SQL names two semantic fact tables.  Origin_Data
        deliberately contains files, not a second warehouse, so the aliases
        below are explicit projections from the delivered loan-order CSV.  The
        mapping is intentionally narrow: if the expected source CSV or a
        required field is absent, no alias is created and the topic run returns
        a visible ``origin_data_*`` failure instead of silently using unrelated
        data.
        """
        frames: dict[str, pl.LazyFrame] = {}
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
            source_headers = [str(field.get("fieldNameCn") or "") for field in fields]
            if not all(source_headers):
                continue
            source_path = tenant_source.resolve_path(path)
            frames[table_name] = pl.scan_csv(
                source_path,
                schema_overrides={header: pl.String for header in source_headers},
                infer_schema_length=0,
            ).rename(dict(zip(source_headers, columns, strict=True))).with_columns(
                *[
                    pl.col(str(field["fieldNameEn"])).cast(_polars_type(field.get("type")), strict=False)
                    for field in fields
                    if _polars_type(field.get("type")) is not pl.String
                ]
            )
            imported_tables[table_name] = set(columns)
        self._create_legacy_topic_views(frames, imported_tables, tenant_id)
        return frames

    @staticmethod
    def _create_legacy_topic_views(
        frames: dict[str, pl.LazyFrame],
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
        normalized_tenant = pl.when(pl.col("tenant_id") == "*").then(pl.lit(tenant_id)).otherwise(pl.col("tenant_id")).alias("tenant_id")
        if loan_source:
            source = frames[loan_source]
            loan = source.select(
                normalized_tenant,
                "branch_name", "product_line", "customer_segment",
                pl.col("month").alias("stat_week"),
                pl.col("drawdown_amount").alias("loan_amount"),
                "loan_balance",
                pl.col("drawdown_amount").alias("new_balance"),
                pl.when(pl.col("loan_balance").cast(pl.Float64, strict=False) == 0).then(None).otherwise(pl.col("m1_overdue_balance").cast(pl.Float64, strict=False) / pl.col("loan_balance").cast(pl.Float64, strict=False)).alias("m1_overdue_rate"),
            )
            frames["loan_operation_fact"] = loan
            frames["weekly_core_metrics_fact"] = loan.select("tenant_id", "stat_week", "loan_balance", "loan_amount", "new_balance")

        voice_source = next(
            (
                table_name
                for table_name, columns in imported_tables.items()
                if {"tenant_id", "branch_name", "product_line", "customer_segment", "month", "channel", "loan_amount", "drawdown_rate", "drawdown_amount", "eligible_amount"}.issubset(columns)
            ),
            "",
        )
        if voice_source:
            source = frames[voice_source]
            eligible = pl.col("eligible_amount").cast(pl.Float64, strict=False)
            drawdown = pl.col("drawdown_amount").cast(pl.Float64, strict=False)
            frames["customer_operation_mart"] = source.select(normalized_tenant, "customer_segment", "product_line", "branch_name", "month", pl.col("drawdown_rate").alias("conversion_rate"), pl.when(eligible == 0).then(0).otherwise(drawdown / eligible).alias("active_customer_count"))
            frames["channel_operation_mart"] = source.select(normalized_tenant, "channel", "month", "product_line", "branch_name", pl.when(drawdown == 0).then(0).otherwise(eligible / drawdown).alias("customer_acquisition_cost"), pl.when(eligible == 0).then(0).otherwise(pl.col("loan_amount").cast(pl.Float64, strict=False) / eligible).alias("roi"))

    @staticmethod
    def _execute(frames: dict[str, pl.LazyFrame], sql: str, tenant_id: str) -> list[dict[str, Any]]:
        tree = sqlglot.parse_one(sql, read="sqlite")
        placeholders = list(tree.find_all(exp.Placeholder))
        if any(str(item.this or "") != "tenant_id" for item in placeholders):
            raise ValueError("topic_sql_unknown_parameter")
        if not placeholders:
            raise ValueError("topic_sql_tenant_binding_required")
        tree = tree.transform(lambda node: exp.Literal.string(tenant_id) if isinstance(node, exp.Placeholder) else node)
        referenced = {table.name for table in tree.find_all(exp.Table)}
        if not referenced.issubset(frames):
            raise KeyError("origin_data_table_not_found")
        context = pl.SQLContext(eager=False)
        for table_name in sorted(referenced):
            context.register(table_name, frames[table_name])
        result = context.execute(tree.sql(dialect="sqlite")).limit(50_000).collect(engine="streaming")
        return result.to_dicts()


def _error_code(exc: Exception) -> str:
    value = str(exc).strip().lower()
    if "table_not_found" in value or "relation" in value and "not found" in value:
        return "origin_data_table_not_found"
    if "no such column" in value:
        return "origin_data_column_not_found"
    if "tenant" in value and "binding" in value:
        return "topic_sql_tenant_binding_required"
    return "topic_data_batch_failed"


def _polars_type(value: Any) -> pl.DataType:
    if pl is None:
        raise RuntimeError("polars_runtime_required")
    normalized = str(value or "").strip().lower()
    if normalized in {"integer", "int", "bigint"}:
        return pl.Int64
    if normalized in {"decimal", "number", "float", "double", "numeric"}:
        return pl.Float64
    if normalized in {"boolean", "bool"}:
        return pl.Boolean
    return pl.String
