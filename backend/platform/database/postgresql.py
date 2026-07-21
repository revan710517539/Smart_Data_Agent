from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_POSTGRES_DDL = Path(__file__).resolve().parent / "postgresql" / "0001_production_schema.sql"
POSTGRES_SCHEMA_VERSION = "0001"
POSTGRES_MIGRATION_LOCK = 7_313_244_101


class PostgreSQLMigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PostgreSQLMigrationResult:
    version: str
    checksum: str
    applied: bool
    execution_ms: int


def normalize_psycopg_url(database_url: str) -> str:
    value = str(database_url or "").strip()
    if value.startswith("postgresql+psycopg://"):
        return "postgresql://" + value[len("postgresql+psycopg://") :]
    if value.startswith("postgresql://"):
        return value
    raise PostgreSQLMigrationError("postgresql_database_url_required")


def apply_postgresql_schema(
    database_url: str,
    ddl_path: str | Path = DEFAULT_POSTGRES_DDL,
    *,
    connection: Any | None = None,
) -> PostgreSQLMigrationResult:
    """Apply the generated production schema once under an advisory lock."""

    path = Path(ddl_path)
    ddl = path.read_text(encoding="utf-8")
    checksum = hashlib.sha256(ddl.encode("utf-8")).hexdigest()
    owns_connection = connection is None
    if connection is None:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - production dependency boundary.
            raise PostgreSQLMigrationError("psycopg_not_installed") from exc
        connection = psycopg.connect(normalize_psycopg_url(database_url), autocommit=False)
    started = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (POSTGRES_MIGRATION_LOCK,))
            cursor.execute("SELECT to_regclass('public.platform_schema_migrations')")
            migration_table_exists = _row_value(cursor.fetchone(), "to_regclass", 0) is not None
            if migration_table_exists:
                cursor.execute(
                    "SELECT checksum FROM platform_schema_migrations WHERE version = %s",
                    (POSTGRES_SCHEMA_VERSION,),
                )
                row = cursor.fetchone()
                if row:
                    if str(_row_value(row, "checksum", 0)) != checksum:
                        raise PostgreSQLMigrationError("postgresql_schema_checksum_drift")
                    connection.commit()
                    return PostgreSQLMigrationResult(
                        version=POSTGRES_SCHEMA_VERSION,
                        checksum=checksum,
                        applied=False,
                        execution_ms=max(0, round((time.perf_counter() - started) * 1000)),
                    )
                cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name LIKE 'platform_%'"
                )
                if int(_row_value(cursor.fetchone(), "count", 0) or 0) > 1:
                    raise PostgreSQLMigrationError("postgresql_unmanaged_schema_detected")
            cursor.execute(ddl)
            elapsed_ms = max(0, round((time.perf_counter() - started) * 1000))
            cursor.execute(
                """
                INSERT INTO platform_schema_migrations(version, name, checksum, execution_ms)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT(version) DO NOTHING
                """,
                (POSTGRES_SCHEMA_VERSION, path.stem, checksum, elapsed_ms),
            )
        connection.commit()
        return PostgreSQLMigrationResult(
            version=POSTGRES_SCHEMA_VERSION,
            checksum=checksum,
            applied=True,
            execution_ms=elapsed_ms,
        )
    except BaseException:
        connection.rollback()
        raise
    finally:
        if owns_connection:
            connection.close()


class PostgreSQLConnectionPool:
    """Application-primary pool with explicit transaction ownership."""

    def __init__(
        self,
        database_url: str,
        *,
        min_size: int = 1,
        max_size: int = 12,
        timeout_seconds: float = 10,
        pool: Any | None = None,
    ) -> None:
        if min_size < 1 or max_size < min_size or max_size > 100:
            raise ValueError("postgresql_pool_size_invalid")
        self.database_url = normalize_psycopg_url(database_url)
        self.min_size = min_size
        self.max_size = max_size
        self.timeout_seconds = timeout_seconds
        if pool is not None:
            self.pool = pool
            return
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
        except ImportError as exc:  # pragma: no cover - production dependency boundary.
            raise RuntimeError("psycopg_pool_not_installed") from exc
        self.pool = ConnectionPool(
            conninfo=self.database_url,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout_seconds,
            kwargs={"autocommit": False, "row_factory": dict_row},
            open=True,
        )

    def connection(self):
        return self.pool.connection(timeout=self.timeout_seconds)

    def health(self) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            with self.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    ready = cursor.fetchone() is not None
            return {
                "ready": ready,
                "adapter": "postgresql_primary",
                "latency_ms": max(0, round((time.perf_counter() - started) * 1000)),
                "min_size": self.min_size,
                "max_size": self.max_size,
            }
        except Exception:
            return {
                "ready": False,
                "adapter": "postgresql_primary",
                "error": "postgresql_primary_unavailable",
                "min_size": self.min_size,
                "max_size": self.max_size,
            }

    def close(self) -> None:
        self.pool.close()


def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]
