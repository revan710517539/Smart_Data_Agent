from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.platform.database.postgresql import (
    PostgreSQLConnectionPool,
    PostgreSQLMigrationError,
    apply_postgresql_schema,
    normalize_psycopg_url,
)
from backend.platform.database.sqlite_maintenance import backup_sqlite_database, inspect_sqlite_database, vacuum_sqlite_database


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self._row = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.connection.calls.append((sql, params))
        normalized = " ".join(str(sql).split())
        if "to_regclass" in normalized:
            self._row = ("platform_schema_migrations",) if self.connection.schema_exists else (None,)
        elif normalized.startswith("SELECT checksum"):
            self._row = (self.connection.applied_checksum,) if self.connection.applied_checksum else None
        elif "COUNT(*) FROM information_schema.tables" in normalized:
            self._row = (self.connection.platform_table_count,)
        elif normalized == "SELECT 1":
            self._row = (1,)
        else:
            self._row = None

    def fetchone(self):
        return self._row


class FakeConnection:
    def __init__(self, *, schema_exists=False, checksum="", table_count=0):
        self.schema_exists = schema_exists
        self.applied_checksum = checksum
        self.platform_table_count = table_count
        self.calls = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeConnectionContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self):
        self.connection_value = FakeConnection()
        self.timeout = None
        self.closed = False

    def connection(self, timeout):
        self.timeout = timeout
        return FakeConnectionContext(self.connection_value)

    def close(self):
        self.closed = True


class PostgreSQLRuntimeTest(unittest.TestCase):
    def test_sqlite_development_database_has_verified_backup_checkpoint_and_vacuum(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "platform.sqlite"
            backup_path = Path(tmpdir) / "backups" / "platform.sqlite"
            connection = sqlite3.connect(db_path)
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("CREATE TABLE facts(id INTEGER PRIMARY KEY, value TEXT)")
            connection.execute("INSERT INTO facts(value) VALUES ('verified')")
            connection.commit()
            connection.close()
            backup = backup_sqlite_database(db_path, backup_path)
            self.assertEqual(backup.integrity, "ok")
            restored = sqlite3.connect(backup_path)
            try:
                self.assertEqual(restored.execute("SELECT value FROM facts").fetchone()[0], "verified")
            finally:
                restored.close()
            self.assertEqual(vacuum_sqlite_database(db_path).integrity, "ok")
            self.assertEqual(inspect_sqlite_database(db_path).integrity, "ok")

    def test_generated_schema_migration_is_locked_checksum_guarded_and_idempotent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            ddl_path = Path(tmpdir) / "0001.sql"
            ddl = "CREATE TABLE platform_schema_migrations(version text primary key, checksum text);"
            ddl_path.write_text(ddl, encoding="utf-8")
            checksum = hashlib.sha256(ddl.encode("utf-8")).hexdigest()
            fresh = FakeConnection()
            result = apply_postgresql_schema("postgresql://db/platform", ddl_path, connection=fresh)
            self.assertTrue(result.applied)
            self.assertEqual(result.checksum, checksum)
            self.assertTrue(any("pg_advisory_xact_lock" in str(call[0]) for call in fresh.calls))
            self.assertTrue(any(str(call[0]) == ddl for call in fresh.calls))
            self.assertEqual(fresh.commits, 1)

            existing = FakeConnection(schema_exists=True, checksum=checksum)
            second = apply_postgresql_schema("postgresql://db/platform", ddl_path, connection=existing)
            self.assertFalse(second.applied)
            self.assertFalse(any(str(call[0]) == ddl for call in existing.calls))

            drifted = FakeConnection(schema_exists=True, checksum="0" * 64)
            with self.assertRaisesRegex(PostgreSQLMigrationError, "checksum_drift"):
                apply_postgresql_schema("postgresql://db/platform", ddl_path, connection=drifted)
            self.assertEqual(drifted.rollbacks, 1)

    def test_application_pool_health_and_url_normalization(self) -> None:
        pool = FakePool()
        runtime = PostgreSQLConnectionPool(
            "postgresql+psycopg://db/platform",
            min_size=2,
            max_size=12,
            timeout_seconds=3,
            pool=pool,
        )
        self.assertEqual(runtime.database_url, "postgresql://db/platform")
        self.assertTrue(runtime.health()["ready"])
        self.assertEqual(pool.timeout, 3)
        runtime.close()
        self.assertTrue(pool.closed)
        with self.assertRaises(PostgreSQLMigrationError):
            normalize_psycopg_url("sqlite:///tmp/db")


if __name__ == "__main__":
    unittest.main()
