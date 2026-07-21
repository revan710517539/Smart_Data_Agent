from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend.platform.database import MigrationDriftError, apply_migrations, migration_status
from backend.platform.database.schema_catalog import TABLES, validate_catalog
from backend.platform.bootstrap import build_local_platform


class SchemaContractsTest(unittest.TestCase):
    def test_auth_schema_declares_global_super_admin_constraints(self) -> None:
        schema = Path("backend/authz/schema.sql").read_text(encoding="utf-8")

        self.assertIn("uq_auth_roles_single_global_super_admin", schema)
        self.assertIn("role_level = 100 AND tenant_id IS NULL", schema)
        self.assertIn("uq_auth_user_roles_global_role", schema)
        self.assertIn("tenant_id BIGINT REFERENCES auth_tenants", schema)

    def test_platform_schema_declares_agent_group_and_eval_tables(self) -> None:
        schema = Path("backend/platform/schema.sql").read_text(encoding="utf-8")

        self.assertIn("platform_agent_groups", schema)
        self.assertIn("platform_agent_group_members", schema)
        self.assertIn("platform_evaluations", schema)
        self.assertIn("platform_model_integrations", schema)
        self.assertIn("platform_data_connections", schema)
        self.assertIn("platform_system_data_params", schema)
        self.assertIn("platform_data_asset_items", schema)
        self.assertIn("permission_compliance_score", schema)

    def test_sqlite_migrations_are_idempotent_and_checksum_protected(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            migration_dir = root / "migrations"
            migration_dir.mkdir()
            migration = migration_dir / "0001_initial.sql"
            migration.write_text(
                "CREATE TABLE example_items (item_id TEXT PRIMARY KEY, name TEXT NOT NULL);",
                encoding="utf-8",
            )
            db_path = root / "platform.sqlite"

            first = apply_migrations(db_path, migration_dir)
            second = apply_migrations(db_path, migration_dir)

            self.assertEqual(first.applied, ("0001",))
            self.assertEqual(second.applied, ())
            self.assertEqual(migration_status(db_path)["current_version"], "0001")

            migration.write_text(
                "CREATE TABLE example_items (item_id TEXT PRIMARY KEY, changed_name TEXT NOT NULL);",
                encoding="utf-8",
            )
            with self.assertRaises(MigrationDriftError):
                apply_migrations(db_path, migration_dir)

    def test_failed_migration_rolls_back_schema_and_version(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            migration_dir = root / "migrations"
            migration_dir.mkdir()
            (migration_dir / "0001_broken.sql").write_text(
                """
                CREATE TABLE should_not_survive (id TEXT PRIMARY KEY);
                INSERT INTO missing_table(id) VALUES ('broken');
                """,
                encoding="utf-8",
            )
            db_path = root / "platform.sqlite"

            with self.assertRaises(Exception):
                apply_migrations(db_path, migration_dir)

            import sqlite3

            connection = sqlite3.connect(db_path)
            try:
                table = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'should_not_survive'"
                ).fetchone()
                applied = connection.execute("SELECT COUNT(*) FROM platform_schema_migrations").fetchone()[0]
            finally:
                connection.close()
            self.assertIsNone(table)
            self.assertEqual(applied, 0)

    def test_production_schema_catalog_and_per_table_docs_do_not_drift(self) -> None:
        validate_catalog()
        self.assertEqual(len(TABLES), 99)
        self.assertEqual(len({table.name for table in TABLES}), 99)

        docs_dir = Path("docs/database_tables")
        actual_docs = {path.stem for path in docs_dir.glob("*.md") if path.name != "README.md"}
        self.assertEqual(actual_docs, {table.name for table in TABLES})

        ddl = Path("backend/platform/database/postgresql/0001_production_schema.sql").read_text(encoding="utf-8")
        self.assertEqual(ddl.count("CREATE TABLE "), 99)
        self.assertIn("platform_market_observations", ddl)
        self.assertIn("platform_operating_system_mappings", ddl)
        self.assertIn("platform_analysis_evidence", ddl)
        self.assertIn("platform_report_block_sources", ddl)
        self.assertIn("platform_acquisition_repair_proposals", ddl)

        subprocess.run(
            [sys.executable, "scripts/generate_database_schema.py", "--check"],
            check=True,
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
        )

    def test_sqlite_bootstrap_uses_migrations_instead_of_store_ddl(self) -> None:
        init_schema_targets = (
            "backend.authz.sqlite_repository.SQLitePolicyRepository.init_schema",
            "backend.platform.repository.SQLiteAnalysisTaskRepository.init_schema",
            "backend.platform.knowledge.SQLiteKnowledgeStore.init_schema",
            "backend.platform.assets.SQLiteDataAssetStore.init_schema",
            "backend.platform.application.SQLiteApplicationStore.init_schema",
            "backend.platform.memory.SQLiteMemoryStore.init_schema",
            "backend.platform.metrics.SQLiteMetricDictionaryStore.init_schema",
            "backend.platform.settings.SQLiteSystemConfigStore.init_schema",
            "backend.platform.reports.SQLiteReportStore.init_schema",
            "backend.platform.audit.SQLiteAuditEventStore.init_schema",
            "backend.platform.access.SQLiteUserDirectoryStore.init_schema",
        )
        with TemporaryDirectory() as tmpdir, ExitStack() as stack:
            for target in init_schema_targets:
                stack.enter_context(patch(target, side_effect=AssertionError(f"Store DDL called: {target}")))
            services = build_local_platform(db_path=Path(tmpdir) / "platform.sqlite")
            try:
                self.assertTrue(services.permission_broker.enforcer.repository.list_roles())
                self.assertEqual(migration_status(Path(tmpdir) / "platform.sqlite")["current_version"], "0025")
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
