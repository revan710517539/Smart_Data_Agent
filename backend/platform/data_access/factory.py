from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Protocol

from .json_warehouse import JSONDataWarehouse
from .csv_warehouse import CSVObjectDataWarehouse
from .doris_warehouse import DorisDataWarehouse
from .hive_warehouse import HiveDataWarehouse
from .postgresql_warehouse import PostgreSQLDataWarehouse
from .sql_warehouse import SQLDataWarehouse


class DataWarehouse(Protocol):
    data_source_name: str

    def list_datasets(self) -> list[dict[str, Any]]:
        ...

    def metric_universe(self) -> set[str]:
        ...

    def dimension_universe(self) -> set[str]:
        ...

    def has_dataset(self, dataset_id: str) -> bool:
        ...

    def query(
        self,
        dataset_id: str,
        tenant_id: str,
        metric: str,
        dimension: str,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> Any:
        ...


class UnconfiguredDataWarehouse:
    """Fail closed until a governed production analytical source is configured."""

    data_source_name = "production_data_source_not_configured"

    def list_datasets(self) -> list[dict[str, Any]]:
        return []

    def metric_universe(self) -> set[str]:
        return set()

    def dimension_universe(self) -> set[str]:
        return set()

    def has_dataset(self, dataset_id: str) -> bool:
        return False

    def query(
        self,
        dataset_id: str,
        tenant_id: str,
        metric: str,
        dimension: str,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> Any:
        raise RuntimeError("production_data_source_not_configured")


class GovernedCSVDataWarehouse(UnconfiguredDataWarehouse):
    """Marker for the Origin/Topic CSV catalog executed by the selected-table path."""

    data_source_name = "governed_origin_topic_csv"

    def query(
        self,
        dataset_id: str,
        tenant_id: str,
        metric: str,
        dimension: str,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> Any:
        raise RuntimeError("governed_csv_table_selection_required")


def build_data_warehouse_from_env() -> tuple[DataWarehouse, str]:
    """Build the local semantic warehouse from environment configuration.

    Starts without a semantic warehouse until a governed production source is
    configured. Data Management remains available through the selected
    institution's delivered CSV catalog; semantic analysis fails closed instead
    of returning mock data.
    """

    mode = os.getenv("SMART_DATA_AGENT_DATA_WAREHOUSE", "").strip().lower()
    if mode in {"", "unconfigured", "production_pending"}:
        warehouse = UnconfiguredDataWarehouse()
        return warehouse, warehouse.data_source_name
    if mode in {"json", "mock", "json_mock"}:
        raise ValueError("mock_data_warehouse_removed: configure a governed production warehouse instead.")
    if mode == "csv":
        warehouse = GovernedCSVDataWarehouse()
        return warehouse, warehouse.data_source_name
    if mode in {"sqlite", "sql", "dbapi"}:
        db_path = os.getenv("SMART_DATA_AGENT_SQLITE_WAREHOUSE_PATH", "").strip()
        catalog_path = os.getenv("SMART_DATA_AGENT_SQL_WAREHOUSE_CATALOG", "").strip()
        if not db_path:
            raise ValueError("SMART_DATA_AGENT_SQLITE_WAREHOUSE_PATH is required for sqlite warehouse mode.")
        if not catalog_path:
            raise ValueError("SMART_DATA_AGENT_SQL_WAREHOUSE_CATALOG is required for sqlite warehouse mode.")
        warehouse = SQLDataWarehouse(
            lambda: sqlite3.connect(db_path),
            load_sql_dataset_catalog(catalog_path),
        )
        return warehouse, warehouse.data_source_name
    if mode in {"postgres", "postgresql", "postgresql_dbapi"}:
        database_url = (
            os.getenv("SMART_DATA_AGENT_WAREHOUSE_DATABASE_URL", "").strip()
            or os.getenv("SMART_DATA_AGENT_DATABASE_URL", "").strip()
        )
        catalog_path = os.getenv("SMART_DATA_AGENT_SQL_WAREHOUSE_CATALOG", "").strip()
        if not database_url:
            raise ValueError("SMART_DATA_AGENT_WAREHOUSE_DATABASE_URL is required for PostgreSQL warehouse mode.")
        if not catalog_path:
            raise ValueError("SMART_DATA_AGENT_SQL_WAREHOUSE_CATALOG is required for PostgreSQL warehouse mode.")
        warehouse = PostgreSQLDataWarehouse(
            database_url,
            load_sql_dataset_catalog(catalog_path),
            min_pool_size=int(os.getenv("SMART_DATA_AGENT_WAREHOUSE_POOL_MIN", "1")),
            max_pool_size=int(os.getenv("SMART_DATA_AGENT_WAREHOUSE_POOL_MAX", "10")),
            statement_timeout_ms=int(os.getenv("SMART_DATA_AGENT_WAREHOUSE_STATEMENT_TIMEOUT_MS", "30000")),
        )
        return warehouse, warehouse.data_source_name
    if mode in {"csv_object", "object_csv"}:
        catalog_path = os.getenv("SMART_DATA_AGENT_SQL_WAREHOUSE_CATALOG", "").strip()
        if not catalog_path:
            raise ValueError("SMART_DATA_AGENT_SQL_WAREHOUSE_CATALOG is required for CSV/object warehouse mode.")
        warehouse = CSVObjectDataWarehouse(
            load_sql_dataset_catalog(catalog_path),
            environment=os.getenv("SMART_DATA_AGENT_ENV", "development").strip().lower(),
            max_object_bytes=int(os.getenv("SMART_DATA_AGENT_CSV_MAX_OBJECT_BYTES", str(50 * 1024 * 1024))),
        )
        return warehouse, warehouse.data_source_name
    if mode in {"doris", "apache_doris"}:
        database_url = os.getenv("SMART_DATA_AGENT_DORIS_DATABASE_URL", "").strip()
        catalog_path = os.getenv("SMART_DATA_AGENT_SQL_WAREHOUSE_CATALOG", "").strip()
        if not database_url or not catalog_path:
            raise ValueError("Doris mode requires SMART_DATA_AGENT_DORIS_DATABASE_URL and SMART_DATA_AGENT_SQL_WAREHOUSE_CATALOG.")
        warehouse = DorisDataWarehouse(
            database_url,
            load_sql_dataset_catalog(catalog_path),
            min_pool_size=int(os.getenv("SMART_DATA_AGENT_WAREHOUSE_POOL_MIN", "1")),
            max_pool_size=int(os.getenv("SMART_DATA_AGENT_WAREHOUSE_POOL_MAX", "10")),
            timeout_seconds=float(os.getenv("SMART_DATA_AGENT_WAREHOUSE_CONNECT_TIMEOUT_SECONDS", "10")),
        )
        return warehouse, warehouse.data_source_name
    if mode in {"hive", "hiveserver2"}:
        database_url = os.getenv("SMART_DATA_AGENT_HIVE_DATABASE_URL", "").strip()
        catalog_path = os.getenv("SMART_DATA_AGENT_SQL_WAREHOUSE_CATALOG", "").strip()
        if not database_url or not catalog_path:
            raise ValueError("Hive mode requires SMART_DATA_AGENT_HIVE_DATABASE_URL and SMART_DATA_AGENT_SQL_WAREHOUSE_CATALOG.")
        warehouse = HiveDataWarehouse(
            database_url,
            load_sql_dataset_catalog(catalog_path),
            min_pool_size=int(os.getenv("SMART_DATA_AGENT_WAREHOUSE_POOL_MIN", "0")),
            max_pool_size=int(os.getenv("SMART_DATA_AGENT_WAREHOUSE_POOL_MAX", "8")),
            timeout_seconds=float(os.getenv("SMART_DATA_AGENT_WAREHOUSE_CONNECT_TIMEOUT_SECONDS", "15")),
        )
        return warehouse, warehouse.data_source_name
    raise ValueError(f"Unsupported SMART_DATA_AGENT_DATA_WAREHOUSE: {mode}")


def load_sql_dataset_catalog(path: str | Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("datasets"), dict):
        return payload["datasets"]
    if isinstance(payload, dict):
        return payload
    raise ValueError("SQL warehouse catalog must be an object or contain a datasets object.")
