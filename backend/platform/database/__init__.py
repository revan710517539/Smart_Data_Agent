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
from .mysql import (
    MySQLConnectionPool,
    MySQLMigrationError,
    MySQLMigrationResult,
    apply_mysql_schema,
    mysql_tls_configured,
    parse_mysql_url,
)
from .mysql_compat import (
    MySQLSQLTranslationError,
    MySQLStoreConnectionPool,
    TranslatedSQL,
    translate_postgresql_sql,
)

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
    "MySQLConnectionPool",
    "MySQLMigrationError",
    "MySQLMigrationResult",
    "apply_mysql_schema",
    "mysql_tls_configured",
    "parse_mysql_url",
    "MySQLSQLTranslationError",
    "MySQLStoreConnectionPool",
    "TranslatedSQL",
    "translate_postgresql_sql",
]
