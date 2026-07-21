from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_MIGRATION_DIR = Path(__file__).resolve().parent / "sql"


class MigrationDriftError(RuntimeError):
    """Raised when an already-applied migration file was modified."""


@dataclass(frozen=True)
class MigrationResult:
    applied: tuple[str, ...]
    current_version: str
    schema_count: int


def apply_migrations(
    db_path: str | Path,
    migration_dir: str | Path = DEFAULT_MIGRATION_DIR,
) -> MigrationResult:
    """Apply immutable SQLite migrations in lexical order.

    The project still supports SQLite for local/single-node deployments.  This
    runner makes schema changes explicit and checksum-protected so production
    adapters can apply the equivalent PostgreSQL migrations without relying on
    Store constructors to mutate schema at runtime.
    """

    root = Path(migration_dir)
    migration_files = sorted(root.glob("*.sql"))
    connection = sqlite3.connect(str(db_path), timeout=30)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_schema_migrations (
                version TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL,
                execution_ms INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.commit()

        applied_rows = connection.execute(
            "SELECT version, checksum FROM platform_schema_migrations ORDER BY version"
        ).fetchall()
        applied_checksums = {str(row[0]): str(row[1]) for row in applied_rows}
        applied_now: list[str] = []
        for path in migration_files:
            version, name = _migration_identity(path)
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            existing_checksum = applied_checksums.get(version)
            if existing_checksum:
                if existing_checksum != checksum:
                    raise MigrationDriftError(
                        f"Migration {version} was modified after application: {path.name}"
                    )
                continue
            started = datetime.now(timezone.utc)
            applied_at = started.isoformat()
            migration_script = f"""BEGIN IMMEDIATE;
{sql}
INSERT INTO platform_schema_migrations(
    version, name, checksum, applied_at, execution_ms
) VALUES (
    {_sql_literal(version)},
    {_sql_literal(name)},
    {_sql_literal(checksum)},
    {_sql_literal(applied_at)},
    0
);
PRAGMA user_version = {_numeric_version(version)};
COMMIT;
"""
            rebuilds_checked_table = version == "0024"
            try:
                if rebuilds_checked_table:
                    connection.execute("PRAGMA foreign_keys = OFF")
                connection.executescript(migration_script)
                elapsed_ms = max(0, round((datetime.now(timezone.utc) - started).total_seconds() * 1000))
                connection.execute(
                    "UPDATE platform_schema_migrations SET execution_ms = ? WHERE version = ?",
                    (elapsed_ms, version),
                )
                connection.commit()
            except sqlite3.IntegrityError:
                connection.rollback()
                concurrent_row = connection.execute(
                    "SELECT checksum FROM platform_schema_migrations WHERE version = ?",
                    (version,),
                ).fetchone()
                if concurrent_row and str(concurrent_row[0]) == checksum:
                    continue
                if concurrent_row:
                    raise MigrationDriftError(
                        f"Migration {version} was concurrently applied with a different checksum"
                    )
                raise
            except BaseException:
                connection.rollback()
                raise
            finally:
                if rebuilds_checked_table:
                    connection.execute("PRAGMA foreign_keys = ON")
                    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
                    if violations:
                        raise RuntimeError(f"Migration {version} left invalid foreign keys: {violations[:3]}")
            applied_now.append(version)

        status = migration_status(connection)
        return MigrationResult(
            applied=tuple(applied_now),
            current_version=status["current_version"],
            schema_count=status["schema_count"],
        )
    finally:
        connection.close()


def migration_status(connection_or_path: sqlite3.Connection | str | Path) -> dict[str, object]:
    owns_connection = not isinstance(connection_or_path, sqlite3.Connection)
    connection = (
        sqlite3.connect(str(connection_or_path))
        if owns_connection
        else connection_or_path
    )
    try:
        exists = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'platform_schema_migrations'
            """
        ).fetchone()
        if not exists:
            return {"current_version": "0", "schema_count": 0, "migrations": []}
        rows = connection.execute(
            """
            SELECT version, name, checksum, applied_at, execution_ms
            FROM platform_schema_migrations
            ORDER BY version
            """
        ).fetchall()
        migrations = [
            {
                "version": str(row[0]),
                "name": str(row[1]),
                "checksum": str(row[2]),
                "applied_at": str(row[3]),
                "execution_ms": int(row[4] or 0),
            }
            for row in rows
        ]
        return {
            "current_version": migrations[-1]["version"] if migrations else "0",
            "schema_count": len(migrations),
            "migrations": migrations,
        }
    finally:
        if owns_connection:
            connection.close()


def _migration_identity(path: Path) -> tuple[str, str]:
    version, separator, name = path.stem.partition("_")
    if not separator or not version.isdigit() or not name:
        raise ValueError(f"Invalid migration filename: {path.name}")
    return version, name


def _numeric_version(version: str) -> int:
    return min(int(version), 2_147_483_647)


def _sql_literal(value: str) -> str:
    """Quote trusted migration metadata for an atomic executescript call."""

    return "'" + value.replace("'", "''") + "'"
