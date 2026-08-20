from __future__ import annotations

from datetime import datetime
import unittest

from backend.platform.database.mysql_compat import (
    MySQLSQLTranslationError,
    MySQLStoreConnectionPool,
    translate_postgresql_sql,
)


class MySQLCompatibilityTest(unittest.TestCase):
    def test_pool_connection_clears_implicit_read_transaction_on_return(self) -> None:
        class Connection:
            def __init__(self) -> None:
                self.rollbacks = 0

            def rollback(self) -> None:
                self.rollbacks += 1

        class Context:
            def __init__(self, connection) -> None:
                self.value = connection

            def __enter__(self):
                return self.value

            def __exit__(self, *args):
                return False

        class Pool:
            def __init__(self) -> None:
                self.value = Connection()

            def connection(self):
                return Context(self.value)

        raw = Pool()
        with MySQLStoreConnectionPool(raw).connection():
            pass
        self.assertEqual(raw.value.rollbacks, 1)

    def test_json_cast_upsert_and_returning_are_translated(self) -> None:
        translated = translate_postgresql_sql(
            """
            INSERT INTO platform_analysis_artifacts(
                analysis_task_id, revision, artifact_type, content
            ) VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (analysis_task_id, revision, artifact_type)
            DO UPDATE SET content = EXCLUDED.content, updated_at = now()
            RETURNING analysis_artifact_id
            """,
            ("task-1", 1, "chart", "{}"),
        )

        self.assertNotIn("::jsonb", translated.sql)
        self.assertNotIn("RETURNING", translated.sql)
        self.assertIn("ON DUPLICATE KEY UPDATE", translated.sql)
        self.assertIn("content = VALUES(content)", translated.sql)
        self.assertIn("UTC_TIMESTAMP(6)", translated.sql)
        self.assertEqual(translated.returning, ("analysis_artifact_id",))

    def test_any_ilike_epoch_filter_and_json_path_are_translated(self) -> None:
        translated = translate_postgresql_sql(
            """
            SELECT EXTRACT(EPOCH FROM created_at)::bigint AS created_epoch,
                   COUNT(*) FILTER (WHERE status = 'ok') AS ok_count
            FROM platform_runtime_events
            WHERE title ILIKE %s
              AND status = ANY(%s)
              AND capabilities ->> 'applicationModule' = %s
            ORDER BY created_at NULLS LAST
            """,
            ("%loan%", ["ok", "error"], "analysis"),
        )

        self.assertIn("UNIX_TIMESTAMP(created_at)", translated.sql)
        self.assertIn("SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END)", translated.sql)
        self.assertIn("LOWER(title) LIKE LOWER(%s)", translated.sql)
        self.assertIn("status IN (%s, %s)", translated.sql)
        self.assertIn("JSON_UNQUOTE(JSON_EXTRACT(capabilities, '$.applicationModule'))", translated.sql)
        self.assertIn("(created_at IS NULL), created_at", translated.sql)
        self.assertEqual(translated.params, ("%loan%", "ok", "error", "analysis"))

    def test_empty_any_is_fail_closed(self) -> None:
        translated = translate_postgresql_sql(
            "SELECT * FROM platform_memory_records WHERE status = ANY(%s)",
            ([],),
        )
        self.assertIn("0 = 1", translated.sql)
        self.assertEqual(translated.params, ())

    def test_insert_shape_accepts_case_expression_without_splitting_values(self) -> None:
        translated = translate_postgresql_sql(
            """
            INSERT INTO platform_data_connections(
                tenant_id, connection_code, last_verified_at, health_summary
            ) VALUES (
                %s, %s, CASE WHEN %s = 'verified' THEN now() END, %s::jsonb
            )
            ON CONFLICT (tenant_id, connection_code) DO UPDATE SET
                health_summary = EXCLUDED.health_summary
            RETURNING connection_id
            """,
            ("tenant", "connection", "verified", "{}"),
        )
        self.assertIn("CASE WHEN %s = 'verified' THEN UTC_TIMESTAMP(6) END", translated.sql)
        self.assertEqual(translated.returning, ("connection_id",))

    def test_iso_timestamp_parameters_are_normalized_to_utc_datetime(self) -> None:
        translated = translate_postgresql_sql(
            "INSERT INTO snapshots(snapshot_at, label) VALUES (%s::timestamptz, %s)",
            ("2026-07-10T10:00:00+08:00", "2026-07-10T10:00:00 is a label"),
        )
        self.assertEqual(translated.params[0], datetime(2026, 7, 10, 2, 0, 0))
        self.assertEqual(translated.params[1], "2026-07-10T10:00:00 is a label")

    def test_null_safe_equality_is_translated(self) -> None:
        translated = translate_postgresql_sql(
            "SELECT * FROM partitions WHERE org_unit_id IS NOT DISTINCT FROM %s",
            (None,),
        )
        self.assertIn("org_unit_id <=> %s", translated.sql)
        self.assertEqual(translated.params, (None,))

    def test_skip_locked_limit_is_reordered_and_of_alias_removed(self) -> None:
        translated = translate_postgresql_sql(
            "SELECT id FROM jobs ORDER BY created_at FOR UPDATE OF jobs SKIP LOCKED LIMIT %s",
            (50,),
        )
        self.assertIn("ORDER BY created_at LIMIT %s FOR UPDATE SKIP LOCKED", translated.sql)
        self.assertNotIn("OF jobs", translated.sql)

    def test_coalesce_on_conflict_target_is_translated(self) -> None:
        translated = translate_postgresql_sql(
            """
            INSERT INTO auth_role_assignments(tenant_id, user_id, role_id, granted_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid), user_id, role_id)
            DO UPDATE SET granted_by = EXCLUDED.granted_by, granted_at = now(), expires_at = NULL
            """,
            ("tenant-key", "user-key", "role-key", "grantor-key"),
        )
        self.assertNotIn("ON CONFLICT", translated.sql)
        self.assertIn("ON DUPLICATE KEY UPDATE", translated.sql)
        self.assertIn("granted_by = VALUES(granted_by)", translated.sql)
        self.assertIn("UTC_TIMESTAMP(6)", translated.sql)
        self.assertEqual(translated.params, ("tenant-key", "user-key", "role-key", "grantor-key"))

    def test_unknown_postgresql_syntax_is_rejected(self) -> None:
        with self.assertRaisesRegex(MySQLSQLTranslationError, "mysql_sql_translation_unsupported"):
            translate_postgresql_sql("SELECT value::money FROM ledger")


if __name__ == "__main__":
    unittest.main()
