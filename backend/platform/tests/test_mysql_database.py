from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock

from backend.platform.database.mysql import (
    MYSQL_ADDITIVE_MIGRATION_DIR,
    MYSQL_SCHEMA_PATH,
    MySQLConnectionPool,
    _creates_schema_migration_table,
    parse_mysql_url,
    split_mysql_statements,
)


class MySQLDatabaseContractTest(unittest.TestCase):
    def test_pool_never_exceeds_max_size_under_concurrent_burst(self) -> None:
        guard = Lock()
        created = 0
        peak = 0
        barrier = Barrier(3)

        class Connection:
            open = True

            def ping(self, reconnect=True):
                return None

            def rollback(self):
                return None

            def close(self):
                self.open = False

        def connector(**options):
            nonlocal created, peak
            del options
            with guard:
                created += 1
                peak = max(peak, created)
            return Connection()

        pool = MySQLConnectionPool(
            "mysql://test@127.0.0.1/test",
            min_size=1,
            max_size=3,
            timeout_seconds=2,
            connector=connector,
        )

        def borrow(index: int) -> int:
            with pool.connection():
                if index < 3:
                    barrier.wait(timeout=2)
                return index

        with ThreadPoolExecutor(max_workers=20) as executor:
            results = list(executor.map(borrow, range(100)))
        try:
            self.assertEqual(results, list(range(100)))
            self.assertLessEqual(peak, 3)
            self.assertLessEqual(pool._created, 3)
        finally:
            pool.close()

    def test_url_parser_requires_mysql_and_preserves_encoded_secret(self) -> None:
        parsed = parse_mysql_url("mysql+pymysql://sda:p%40ss@127.0.0.1:3307/smart_data_agent?ssl_mode=required")
        self.assertEqual(parsed["database"], "smart_data_agent")
        self.assertEqual(parsed["password"], "p@ss")
        self.assertEqual(parsed["init_command"], "SET time_zone = '+00:00'")
        self.assertIn("ssl", parsed)
        with self.assertRaisesRegex(ValueError, "mysql_database_url_required"):
            parse_mysql_url("postgresql://db/smart_data_agent")

    def test_generated_schema_is_mysql_only_and_complete(self) -> None:
        ddl = Path(MYSQL_SCHEMA_PATH).read_text(encoding="utf-8")
        self.assertEqual(ddl.count("CREATE TABLE "), 106)
        self.assertIn("CREATE TABLE platform_analysis_workspaces", ddl)
        self.assertIn("CREATE TABLE platform_analysis_result_cache", ddl)
        for forbidden in ("JSONB", "TIMESTAMPTZ", "gen_random_uuid", "::jsonb", "COMMENT ON"):
            self.assertNotIn(forbidden, ddl)
        statements = split_mysql_statements(ddl)
        self.assertEqual(statements[0], "SET NAMES utf8mb4")
        self.assertEqual(statements[1], "SET time_zone = '+00:00'")
        self.assertEqual(sum(_creates_schema_migration_table(item) for item in statements), 1)
        additive = (MYSQL_ADDITIVE_MIGRATION_DIR / "0029_message_board.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS platform_message_board_entries", additive)
        self.assertIn("quote_context JSON", additive)


if __name__ == "__main__":
    unittest.main()
