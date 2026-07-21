from __future__ import annotations

from typing import Any

from .sql_warehouse import SQLDataWarehouse


class _PooledConnectionHandle:
    def __init__(self, pool: Any) -> None:
        self._pool = pool
        self._connection = pool.getconn()
        self._closed = False

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> Any:
        if self._closed:
            raise RuntimeError("postgresql_warehouse_connection_closed")
        return self._connection.execute(sql, parameters)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._pool.putconn(self._connection)


class PostgreSQLDataWarehouse(SQLDataWarehouse):
    """Pooled, read-only PostgreSQL analytical warehouse adapter.

    SQL identifiers still come exclusively from the governed dataset catalog;
    user/tenant/filter values use psycopg parameters.  The pool config applies a
    default read-only transaction and a server-side statement timeout so an API
    request cannot silently become a long-running write-capable session.
    """

    data_source_name = "postgresql_dbapi_warehouse"

    def __init__(
        self,
        database_url: str,
        dataset_catalog: dict[str, dict[str, Any]],
        *,
        min_pool_size: int = 1,
        max_pool_size: int = 10,
        statement_timeout_ms: int = 30_000,
        pool: Any | None = None,
    ) -> None:
        database_url = _normalize_postgresql_url(database_url)
        if not database_url:
            raise ValueError("postgresql_warehouse_database_url_required")
        min_pool_size = max(1, int(min_pool_size))
        max_pool_size = max(min_pool_size, min(int(max_pool_size), 50))
        statement_timeout_ms = max(1_000, min(int(statement_timeout_ms), 300_000))
        if pool is None:
            try:
                from psycopg_pool import ConnectionPool
            except ImportError as exc:  # pragma: no cover - dependency contract.
                raise RuntimeError("psycopg_pool_required_for_postgresql_warehouse") from exc
            options = (
                "-c default_transaction_read_only=on "
                f"-c statement_timeout={statement_timeout_ms} "
                "-c idle_in_transaction_session_timeout=15000"
            )
            pool = ConnectionPool(
                conninfo=database_url,
                min_size=min_pool_size,
                max_size=max_pool_size,
                kwargs={"autocommit": True, "options": options},
                open=True,
            )
        self.pool = pool
        self.pool_limits = {"min": min_pool_size, "max": max_pool_size}
        self.statement_timeout_ms = statement_timeout_ms
        super().__init__(
            lambda: _PooledConnectionHandle(self.pool),
            dataset_catalog,
            parameter_placeholder="%s",
        )

    def close(self) -> None:
        close = getattr(self.pool, "close", None)
        if callable(close):
            close()

    def health(self) -> dict[str, Any]:
        handle = _PooledConnectionHandle(self.pool)
        try:
            row = handle.execute("SELECT 1").fetchone()
            ready = bool(row and int(row[0]) == 1)
        except Exception as exc:
            return {
                "ready": False,
                "adapter": self.data_source_name,
                "error": type(exc).__name__,
                "pool": dict(self.pool_limits),
            }
        finally:
            handle.close()
        return {
            "ready": ready,
            "adapter": self.data_source_name,
            "read_only": True,
            "statement_timeout_ms": self.statement_timeout_ms,
            "pool": dict(self.pool_limits),
        }


def _normalize_postgresql_url(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized.startswith("postgresql+psycopg://"):
        return "postgresql://" + normalized.removeprefix("postgresql+psycopg://")
    if normalized and not normalized.startswith(("postgresql://", "postgres://")):
        raise ValueError("postgresql_warehouse_database_url_must_be_postgresql")
    return normalized
