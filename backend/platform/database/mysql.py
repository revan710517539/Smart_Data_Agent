from __future__ import annotations

import hashlib
import os
import queue
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, unquote, urlparse


MYSQL_SCHEMA_VERSION = "0001"
MYSQL_SCHEMA_PATH = Path(__file__).resolve().parent / "mysql" / "0001_production_schema.sql"
MYSQL_ADDITIVE_MIGRATION_DIR = Path(__file__).resolve().parent / "mysql" / "migrations"
MYSQL_MIGRATION_LOCK = "smart_data_agent_schema_migration"


class MySQLMigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MySQLMigrationResult:
    version: str
    checksum: str
    applied: bool
    execution_ms: int


def parse_mysql_url(database_url: str) -> dict[str, Any]:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise ValueError("mysql_database_url_required")
    database = parsed.path.removeprefix("/").strip()
    if not parsed.hostname or not database:
        raise ValueError("mysql_database_url_incomplete")
    query = parse_qs(parsed.query)
    ssl_enabled = (query.get("ssl") or query.get("ssl_mode") or [""])[0].lower()
    options: dict[str, Any] = {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": unquote(database),
        "charset": "utf8mb4",
        "autocommit": False,
        "connect_timeout": int((query.get("connect_timeout") or ["10"])[0]),
        "read_timeout": int((query.get("read_timeout") or ["30"])[0]),
        "write_timeout": int((query.get("write_timeout") or ["30"])[0]),
        "init_command": "SET time_zone = '+00:00'",
    }
    if ssl_enabled in {"1", "true", "required", "verify_ca", "verify_identity"}:
        ssl: dict[str, Any] = {}
        ca = (query.get("ssl_ca") or [""])[0]
        if ca:
            ssl["ca"] = ca
        options["ssl"] = ssl
    return options


class MySQLConnectionPool:
    """Small bounded DB-API pool with explicit transaction ownership."""

    def __init__(
        self,
        database_url: str,
        *,
        min_size: int = 1,
        max_size: int = 12,
        timeout_seconds: float = 10,
        connector: Any | None = None,
    ) -> None:
        if min_size < 1 or max_size < min_size or max_size > 100:
            raise ValueError("mysql_pool_size_invalid")
        self.database_url = database_url
        self.options = parse_mysql_url(database_url)
        self.min_size = min_size
        self.max_size = max_size
        self.timeout_seconds = timeout_seconds
        self._connector = connector or _pymysql_connect
        self._connections: queue.LifoQueue[Any] = queue.LifoQueue(maxsize=max_size)
        self._created = 0
        self._guard = threading.Lock()
        self._closed = False
        for _ in range(min_size):
            self._connections.put(self._create_connection())

    def _create_connection(self) -> Any:
        with self._guard:
            if self._closed or self._created >= self.max_size:
                raise RuntimeError("mysql_pool_capacity_exhausted")
            self._created += 1
        try:
            return self._connector(**self.options)
        except BaseException:
            with self._guard:
                self._created = max(0, self._created - 1)
            raise

    @contextmanager
    def connection(self) -> Iterator[Any]:
        if self._closed:
            raise RuntimeError("mysql_pool_closed")
        try:
            connection = self._connections.get_nowait()
        except queue.Empty:
            try:
                connection = self._create_connection()
            except RuntimeError as exc:
                if str(exc) != "mysql_pool_capacity_exhausted":
                    raise
                connection = self._connections.get(timeout=self.timeout_seconds)
        try:
            connection.ping(reconnect=True)
            yield connection
        except BaseException:
            try:
                connection.rollback()
            finally:
                if not _connection_open(connection):
                    with self._guard:
                        self._created = max(0, self._created - 1)
                    connection = None
            raise
        finally:
            if connection is not None and not self._closed:
                try:
                    self._connections.put_nowait(connection)
                except queue.Full:
                    connection.close()
                    with self._guard:
                        self._created = max(0, self._created - 1)

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        with self.connection() as connection:
            try:
                connection.begin()
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def health(self) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT VERSION() AS version, @@session.time_zone AS time_zone")
                row = cursor.fetchone() or {}
            return {
                "ready": True,
                "adapter": "mysql_primary",
                "version": str(_value(row, "version", 0) or ""),
                "time_zone": str(_value(row, "time_zone", 1) or ""),
                "latency_ms": max(0, round((time.perf_counter() - started) * 1000)),
                "min_size": self.min_size,
                "max_size": self.max_size,
            }
        except Exception:
            return {
                "ready": False,
                "adapter": "mysql_primary",
                "error": "mysql_primary_unavailable",
                "min_size": self.min_size,
                "max_size": self.max_size,
            }

    def close(self) -> None:
        self._closed = True
        while True:
            try:
                connection = self._connections.get_nowait()
            except queue.Empty:
                break
            try:
                connection.close()
            finally:
                with self._guard:
                    self._created = max(0, self._created - 1)


def apply_mysql_schema(
    database_url: str,
    *,
    connection: Any | None = None,
    schema_path: str | Path = MYSQL_SCHEMA_PATH,
) -> MySQLMigrationResult:
    path = Path(schema_path)
    ddl = path.read_text(encoding="utf-8")
    checksum = hashlib.sha256(ddl.encode("utf-8")).hexdigest()
    owns_connection = connection is None
    if connection is None:
        connection = _pymysql_connect(**parse_mysql_url(database_url))
    started = time.perf_counter()
    lock_acquired = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK(%s, 30)", (MYSQL_MIGRATION_LOCK,))
            lock_acquired = int(_value(cursor.fetchone(), "GET_LOCK(%s, 30)", 0) or 0) == 1
            if not lock_acquired:
                raise MySQLMigrationError("mysql_schema_migration_lock_timeout")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS platform_schema_migrations (
                    version VARCHAR(32) PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    checksum CHAR(64) NOT NULL,
                    applied_at DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
                    execution_ms INTEGER NOT NULL DEFAULT 0
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
                """
            )
            cursor.execute("SELECT checksum FROM platform_schema_migrations WHERE version=%s", (MYSQL_SCHEMA_VERSION,))
            row = cursor.fetchone()
            baseline_applied = False
            if row:
                if str(_value(row, "checksum", 0)) != checksum:
                    raise MySQLMigrationError("mysql_schema_checksum_drift")
            else:
                cursor.execute(
                    "SELECT COUNT(*) AS count FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name LIKE 'platform_%'"
                )
                if int(_value(cursor.fetchone(), "count", 0) or 0) > 1:
                    raise MySQLMigrationError("mysql_unmanaged_schema_detected")
                for statement in split_mysql_statements(ddl):
                    # The migration ledger is bootstrapped above so checksum drift can
                    # be checked before any application table is created.
                    if _creates_schema_migration_table(statement):
                        continue
                    cursor.execute(statement)
                elapsed_ms = max(0, round((time.perf_counter() - started) * 1000))
                cursor.execute(
                    "INSERT INTO platform_schema_migrations(version,name,checksum,execution_ms) VALUES(%s,%s,%s,%s)",
                    (MYSQL_SCHEMA_VERSION, path.stem, checksum, elapsed_ms),
                )
                baseline_applied = True
            _apply_mysql_additive_migrations(cursor)
        connection.commit()
        elapsed_ms = max(0, round((time.perf_counter() - started) * 1000))
        return MySQLMigrationResult(MYSQL_SCHEMA_VERSION, checksum, baseline_applied, elapsed_ms)
    except BaseException:
        connection.rollback()
        raise
    finally:
        if lock_acquired:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT RELEASE_LOCK(%s)", (MYSQL_MIGRATION_LOCK,))
                connection.commit()
            except Exception:
                pass
        if owns_connection:
            connection.close()


def _creates_schema_migration_table(statement: str) -> bool:
    normalized = " ".join(statement.lower().split())
    return normalized.startswith("create table platform_schema_migrations ")


def _apply_mysql_additive_migrations(cursor: Any) -> None:
    if not MYSQL_ADDITIVE_MIGRATION_DIR.exists():
        return
    for path in sorted(MYSQL_ADDITIVE_MIGRATION_DIR.glob("*.sql")):
        version = path.name.split("_", 1)[0]
        if not version.isdigit() or version == MYSQL_SCHEMA_VERSION:
            raise MySQLMigrationError(f"mysql_migration_filename_invalid:{path.name}")
        ddl = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(ddl.encode("utf-8")).hexdigest()
        cursor.execute("SELECT checksum FROM platform_schema_migrations WHERE version=%s", (version,))
        row = cursor.fetchone()
        if row:
            if str(_value(row, "checksum", 0)) != checksum:
                raise MySQLMigrationError(f"mysql_schema_checksum_drift:{version}")
            continue
        started = time.perf_counter()
        for statement in split_mysql_statements(ddl):
            cursor.execute(statement)
        cursor.execute(
            "INSERT INTO platform_schema_migrations(version,name,checksum,execution_ms) VALUES(%s,%s,%s,%s)",
            (version, path.stem, checksum, max(0, round((time.perf_counter() - started) * 1000))),
        )


def split_mysql_statements(ddl: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    quoted: str | None = None
    escaped = False
    for character in ddl:
        if escaped:
            buffer.append(character)
            escaped = False
            continue
        if character == "\\" and quoted:
            buffer.append(character)
            escaped = True
            continue
        if character in {"'", '"', "`"}:
            if quoted == character:
                quoted = None
            elif quoted is None:
                quoted = character
            buffer.append(character)
            continue
        if character == ";" and quoted is None:
            statement = "".join(buffer).strip()
            buffer = []
            if statement:
                statements.append(_strip_leading_comments(statement))
            continue
        buffer.append(character)
    trailing = "".join(buffer).strip()
    if trailing:
        statements.append(_strip_leading_comments(trailing))
    return [statement for statement in statements if statement]


def mysql_tls_configured(database_url: str) -> bool:
    query = parse_qs(urlparse(database_url).query)
    value = (query.get("ssl") or query.get("ssl_mode") or [""])[0].lower()
    return value in {"1", "true", "required", "verify_ca", "verify_identity"}


def _strip_leading_comments(statement: str) -> str:
    return re.sub(r"\A(?:\s*--[^\n]*(?:\n|\Z))+", "", statement).strip()


def _pymysql_connect(**options: Any) -> Any:
    try:
        import pymysql
        from pymysql.cursors import DictCursor
    except ImportError as exc:
        raise RuntimeError("pymysql_not_installed") from exc
    return pymysql.connect(cursorclass=DictCursor, **options)


def _connection_open(connection: Any) -> bool:
    return bool(getattr(connection, "open", True))


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        if key in row:
            return row[key]
        return next(iter(row.values()), None)
    try:
        return row[index]
    except (TypeError, IndexError):
        return None
