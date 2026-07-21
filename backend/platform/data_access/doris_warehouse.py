from __future__ import annotations

import os
import ssl
from typing import Any, Callable
from urllib.parse import unquote, urlparse

import certifi

from backend.platform.security import validate_outbound_url

from .dbapi_pool import DBAPIConnectionPool
from .sql_warehouse import SQLDataWarehouse


class DorisDataWarehouse(SQLDataWarehouse):
    data_source_name = "doris_mysql_warehouse"

    def __init__(
        self,
        database_url: str,
        dataset_catalog: dict[str, dict[str, Any]],
        *,
        min_pool_size: int = 1,
        max_pool_size: int = 10,
        timeout_seconds: float = 10,
        connection_factory: Callable[[], Any] | None = None,
    ) -> None:
        factory = connection_factory or _doris_connection_factory(database_url, timeout_seconds)
        self.pool = DBAPIConnectionPool(
            factory,
            min_size=min_pool_size,
            max_size=max_pool_size,
            timeout_seconds=timeout_seconds,
        )
        super().__init__(self.pool.connection, dataset_catalog, parameter_placeholder="%s")

    def close(self) -> None:
        self.pool.close()


def _doris_connection_factory(database_url: str, timeout_seconds: float) -> Callable[[], Any]:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"mysql", "doris"} or not parsed.hostname or not parsed.path.strip("/"):
        raise ValueError("doris_database_url_invalid")
    validate_outbound_url(f"https://{parsed.hostname}:{parsed.port or 9030}")
    require_tls = os.getenv("SMART_DATA_AGENT_DORIS_TLS", "true").strip().lower() not in {"0", "false", "no"}
    ssl_config = {"ca": os.getenv("SMART_DATA_AGENT_DORIS_SSL_CA", certifi.where())} if require_tls else None

    def connect():
        try:
            import pymysql
        except ImportError as exc:  # pragma: no cover - production dependency boundary.
            raise RuntimeError("pymysql_not_installed") from exc
        connection = pymysql.connect(
            host=parsed.hostname,
            port=parsed.port or 9030,
            user=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            database=parsed.path.strip("/"),
            connect_timeout=max(1, int(timeout_seconds)),
            read_timeout=max(1, int(timeout_seconds)),
            write_timeout=max(1, int(timeout_seconds)),
            ssl=ssl_config,
            autocommit=False,
        )
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION sql_mode = 'ANSI_QUOTES'")
        return connection

    return connect
