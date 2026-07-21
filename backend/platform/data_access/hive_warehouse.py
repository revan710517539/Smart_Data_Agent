from __future__ import annotations

import os
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from backend.platform.security import validate_outbound_url

from .dbapi_pool import DBAPIConnectionPool
from .sql_warehouse import SQLDataWarehouse


class HiveDataWarehouse(SQLDataWarehouse):
    data_source_name = "hive_server2_warehouse"

    def __init__(
        self,
        database_url: str,
        dataset_catalog: dict[str, dict[str, Any]],
        *,
        min_pool_size: int = 0,
        max_pool_size: int = 8,
        timeout_seconds: float = 15,
        connection_factory: Callable[[], Any] | None = None,
    ) -> None:
        factory = connection_factory or _hive_connection_factory(database_url)
        self.pool = DBAPIConnectionPool(
            factory,
            min_size=min_pool_size,
            max_size=max_pool_size,
            timeout_seconds=timeout_seconds,
        )
        super().__init__(self.pool.connection, dataset_catalog, parameter_placeholder="%s")

    def close(self) -> None:
        self.pool.close()


def _hive_connection_factory(database_url: str) -> Callable[[], Any]:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"hive", "hive+https"} or not parsed.hostname:
        raise ValueError("hive_database_url_invalid")
    if os.getenv("SMART_DATA_AGENT_ENV", "development").strip().lower() in {"staging", "production"} and parsed.scheme != "hive+https":
        raise ValueError("hive_tls_required")
    validate_outbound_url(f"https://{parsed.hostname}:{parsed.port or 10000}")
    query = parse_qs(parsed.query)
    auth = str((query.get("auth") or ["NONE"])[0]).upper()
    if auth not in {"NONE", "NOSASL", "LDAP", "KERBEROS", "CUSTOM"}:
        raise ValueError("hive_auth_mode_invalid")

    def connect():
        try:
            from pyhive import hive
        except ImportError as exc:  # pragma: no cover - production dependency boundary.
            raise RuntimeError("pyhive_not_installed") from exc
        return hive.Connection(
            host=parsed.hostname,
            port=parsed.port or 10000,
            username=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            database=parsed.path.strip("/") or "default",
            auth=auth,
            scheme="https" if parsed.scheme == "hive+https" else "binary",
            configuration={"hive.server2.thrift.resultset.default.fetch.size": "1000"},
        )

    return connect
