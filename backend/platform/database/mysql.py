from __future__ import annotations

import hashlib
import os
import queue
import re
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, unquote, urlparse


MYSQL_SCHEMA_VERSION = "0001"
MYSQL_SCHEMA_PATH = Path(__file__).resolve().parent / "mysql" / "0001_production_schema.sql"
MYSQL_ADDITIVE_MIGRATION_DIR = Path(__file__).resolve().parent / "mysql" / "migrations"
MYSQL_MIGRATION_LOCK = "smart_data_agent_schema_migration"
MYSQL_TARGET_VERSION = "8.0.18"
# These exact hashes were applied by the immediately preceding repository
# revision before MySQL 8.0.18-compatible datetime defaults were corrected.
# They are schema-equivalent for already-created databases. Unknown drift still
# fails closed, and new installations always record the current file hashes.
MYSQL_COMPATIBLE_LEGACY_CHECKSUMS = {
    "0001": frozenset({"7c65ac31c6878bb1b11f0095887903251e29ceddae1f85d3328a4c512afbdf3d"}),
    "0029": frozenset({"a0ad5a5c7c8ed85def743ba5c4a22f7d8dc1f5a9c839407eae8253d06910df36"}),
    "0031": frozenset({"b1d0e919ddae36ccc8240bb4d054ada2f40f8dcde08a8c661ffa0888ce4cd35e"}),
}


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
    ssl_enabled = (query.get("ssl") or query.get("ssl_mode") or [""])[0].strip().lower()
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
    if ssl_enabled and ssl_enabled not in {"1", "true", "required", "verify_ca", "verify_identity"}:
        raise ValueError("mysql_ssl_mode_invalid")
    if ssl_enabled in {"1", "true", "required"}:
        options["ssl"] = {}
    elif ssl_enabled in {"verify_ca", "verify_identity"}:
        ca = (query.get("ssl_ca") or [""])[0].strip()
        if not ca:
            raise ValueError("mysql_ssl_ca_required")
        options["ssl"] = {
            "ca": ca,
            "check_hostname": ssl_enabled == "verify_identity",
            "verify_mode": True,
        }
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
        compatible_versions: tuple[str, ...] = (),
        connector: Any | None = None,
    ) -> None:
        if min_size < 1 or max_size < min_size or max_size > 100:
            raise ValueError("mysql_pool_size_invalid")
        self.database_url = database_url
        self.options = parse_mysql_url(database_url)
        self.min_size = min_size
        self.max_size = max_size
        self.timeout_seconds = timeout_seconds
        self.compatible_versions = compatible_versions
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
            version = str(_value(row, "version", 0) or "")
            supported = mysql_version_supported(version, compatible_versions=self.compatible_versions)
            return {
                "ready": supported,
                "adapter": "mysql_primary",
                "version": version,
                "target_version": MYSQL_TARGET_VERSION,
                **({"error": "mysql_version_unsupported"} if not supported else {}),
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
    compatible_versions: tuple[str, ...] = (),
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
            cursor.execute("SELECT VERSION() AS version")
            version = str(_value(cursor.fetchone(), "version", 0) or "")
            if not mysql_version_supported(version, compatible_versions=compatible_versions):
                raise MySQLMigrationError(f"mysql_version_unsupported:{version}")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS platform_schema_migrations (
                    version VARCHAR(32) PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    checksum CHAR(64) NOT NULL,
                    applied_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                    execution_ms INTEGER NOT NULL DEFAULT 0
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
                """
            )
            cursor.execute("SELECT checksum FROM platform_schema_migrations WHERE version=%s", (MYSQL_SCHEMA_VERSION,))
            row = cursor.fetchone()
            baseline_applied = False
            if row:
                if not _checksum_matches(MYSQL_SCHEMA_VERSION, str(_value(row, "checksum", 0)), checksum):
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
            _apply_mysql_additive_migrations(connection, cursor)
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


def _apply_mysql_additive_migrations(connection: Any, cursor: Any) -> None:
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
            if not _checksum_matches(version, str(_value(row, "checksum", 0)), checksum):
                raise MySQLMigrationError(f"mysql_schema_checksum_drift:{version}")
            continue
        started = time.perf_counter()
        statements = split_mysql_statements(ddl)
        attempt_id = str(uuid.uuid4())
        attempts_available = _migration_attempts_table_exists(cursor)
        if attempts_available:
            cursor.execute(
                """
                INSERT INTO platform_schema_migration_attempts(
                    attempt_id,version,name,checksum,status,statement_count,last_statement_index,runner_revision
                ) VALUES(%s,%s,%s,%s,'running',%s,0,%s)
                """,
                (attempt_id, version, path.stem, checksum, len(statements), _runner_revision()),
            )
            connection.commit()
        last_statement_index = 0
        try:
            for last_statement_index, statement in enumerate(statements, start=1):
                cursor.execute(statement)
            elapsed_ms = max(0, round((time.perf_counter() - started) * 1000))
            cursor.execute(
                "INSERT INTO platform_schema_migrations(version,name,checksum,execution_ms) VALUES(%s,%s,%s,%s)",
                (version, path.stem, checksum, elapsed_ms),
            )
            if _migration_attempts_table_exists(cursor):
                if attempts_available:
                    cursor.execute(
                        """
                        UPDATE platform_schema_migration_attempts
                        SET status='succeeded',last_statement_index=%s,finished_at=CURRENT_TIMESTAMP(6),execution_ms=%s
                        WHERE attempt_id=%s
                        """,
                        (last_statement_index, elapsed_ms, attempt_id),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO platform_schema_migration_attempts(
                            attempt_id,version,name,checksum,status,statement_count,last_statement_index,
                            started_at,finished_at,execution_ms,runner_revision
                        ) VALUES(%s,%s,%s,%s,'succeeded',%s,%s,CURRENT_TIMESTAMP(6),CURRENT_TIMESTAMP(6),%s,%s)
                        """,
                        (attempt_id, version, path.stem, checksum, len(statements), last_statement_index, elapsed_ms, _runner_revision()),
                    )
            connection.commit()
        except BaseException as exc:
            connection.rollback()
            if attempts_available:
                try:
                    with connection.cursor() as failure_cursor:
                        failure_cursor.execute(
                            """
                            UPDATE platform_schema_migration_attempts
                            SET status='failed',last_statement_index=%s,error_code=%s,error_summary=%s,
                                finished_at=CURRENT_TIMESTAMP(6),execution_ms=%s
                            WHERE attempt_id=%s
                            """,
                            (
                                last_statement_index,
                                type(exc).__name__[:160],
                                _safe_error_summary(exc),
                                max(0, round((time.perf_counter() - started) * 1000)),
                                attempt_id,
                            ),
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
            raise


def _checksum_matches(version: str, stored: str, current: str) -> bool:
    return stored == current or stored in MYSQL_COMPATIBLE_LEGACY_CHECKSUMS.get(str(version), frozenset())


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
    ca = (query.get("ssl_ca") or [""])[0].strip()
    return value in {"verify_ca", "verify_identity"} and bool(ca)


def mysql_version_supported(version: str, *, compatible_versions: tuple[str, ...] = ()) -> bool:
    actual = str(version or "").split("-", 1)[0].strip()
    return actual == MYSQL_TARGET_VERSION or actual in compatible_versions


def _migration_attempts_table_exists(cursor: Any) -> bool:
    cursor.execute(
        "SELECT COUNT(*) AS count FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=%s",
        ("platform_schema_migration_attempts",),
    )
    return int(_value(cursor.fetchone(), "count", 0) or 0) == 1


def _runner_revision() -> str:
    value = os.getenv("SMART_DATA_AGENT_COMMIT_SHA", "").strip().lower()
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else ""


def _safe_error_summary(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    return (text or type(exc).__name__)[:500]


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
