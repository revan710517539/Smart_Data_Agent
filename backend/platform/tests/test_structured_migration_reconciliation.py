from __future__ import annotations

import unittest

import sqlite3

from scripts.migrate_structured_to_mysql import _columns
from scripts.reconcile_structured_migration import reconcile


class StructuredMigrationReconciliationTest(unittest.TestCase):
    def test_legacy_knowledge_chunks_use_chunk_no(self) -> None:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute(
                "CREATE TABLE platform_knowledge_chunks(chunk_id TEXT PRIMARY KEY, chunk_no INTEGER NOT NULL, content TEXT NOT NULL)"
            )
            self.assertIn("chunk_no", _columns(connection, "platform_knowledge_chunks"))
            self.assertNotIn("chunk_index", _columns(connection, "platform_knowledge_chunks"))
        finally:
            connection.close()

    def test_cutover_requires_shared_rows_and_columns_to_match(self) -> None:
        source = {"sha256": "a" * 64, "tables": {"users": {"rows": 2, "columns": ["id", "name"]}}}
        target = {"tables": {"users": {"rows": 2, "columns": ["id", "name", "created_at"]}}}
        self.assertTrue(reconcile(source, target)["ready_for_cutover"])
        target["tables"]["users"]["rows"] = 1
        self.assertFalse(reconcile(source, target)["ready_for_cutover"])

    def test_missing_target_column_fails_closed(self) -> None:
        source = {"tables": {"metrics": {"rows": 1, "columns": ["id", "version"]}}}
        target = {"tables": {"metrics": {"rows": 1, "columns": ["id"]}}}
        report = reconcile(source, target)
        self.assertEqual(report["comparisons"][0]["missing_target_columns"], ["version"])
        self.assertFalse(report["ready_for_cutover"])


if __name__ == "__main__":
    unittest.main()
