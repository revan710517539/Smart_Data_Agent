"""Database schema migration and verification helpers."""

from .migrator import MigrationDriftError, MigrationResult, apply_migrations, migration_status
from .postgresql import (
    PostgreSQLConnectionPool,
    PostgreSQLMigrationError,
    PostgreSQLMigrationResult,
    apply_postgresql_schema,
)
from .sqlite_maintenance import backup_sqlite_database, inspect_sqlite_database, vacuum_sqlite_database
from .identity import PostgreSQLIdentityResolver

__all__ = [
    "MigrationDriftError",
    "MigrationResult",
    "apply_migrations",
    "migration_status",
    "apply_postgresql_schema",
    "PostgreSQLMigrationError",
    "PostgreSQLMigrationResult",
    "PostgreSQLConnectionPool",
    "backup_sqlite_database",
    "inspect_sqlite_database",
    "vacuum_sqlite_database",
    "PostgreSQLIdentityResolver",
]
