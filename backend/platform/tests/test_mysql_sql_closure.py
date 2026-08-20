from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
REPO_MYSQL = ROOT / "backend" / "platform" / "database" / "mysql"
IMAGE_MYSQL_PATHS = (
    Path("/app/backend/platform/database/mysql"),
    Path("/usr/local/lib/python3.13/site-packages/backend/platform/database/mysql"),
)


class MySQLSQLClosureTest(unittest.TestCase):
    def test_repo_mysql_sql_uses_mysql_8018_datetime_defaults(self) -> None:
        files = sorted(path.relative_to(REPO_MYSQL).as_posix() for path in REPO_MYSQL.rglob("*.sql"))
        self.assertEqual(
            files,
            [
                "0001_production_schema.sql",
                "migrations/0029_message_board.sql",
                "migrations/0030_message_board_status.sql",
                "migrations/0031_user_interaction_events.sql",
            ],
        )
        for path in REPO_MYSQL.rglob("*.sql"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("DEFAULT (UTC_TIMESTAMP(6))", text, path.name)
        schema = (REPO_MYSQL / "0001_production_schema.sql").read_text(encoding="utf-8")
        self.assertIn("DEFAULT CURRENT_TIMESTAMP(6)", schema)
        status = (REPO_MYSQL / "migrations" / "0030_message_board_status.sql").read_text(encoding="utf-8")
        self.assertNotIn("UTC_TIMESTAMP", status)

    def test_closure_script_accepts_the_checked_in_sql(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "check_mysql_sql_closure.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertIn("MySQL SQL closure ok", completed.stdout)

    def test_additive_migrations_keep_expression_defaults_except_datetime(self) -> None:
        for name in ("0029_message_board.sql", "0031_user_interaction_events.sql"):
            text = (REPO_MYSQL / "migrations" / name).read_text(encoding="utf-8")
            self.assertIn("DEFAULT CURRENT_TIMESTAMP(6)", text)
            self.assertNotIn("DEFAULT (UTC_TIMESTAMP(6))", text)
            self.assertIn("DEFAULT (UUID())", text)

    def test_image_mysql_paths_match_when_installed(self) -> None:
        existing = [path for path in IMAGE_MYSQL_PATHS if path.is_dir()]
        if len(existing) < 2:
            self.skipTest("image dual MySQL SQL paths are not present")
        left = {path.relative_to(existing[0]).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in existing[0].rglob("*.sql")}
        right = {path.relative_to(existing[1]).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in existing[1].rglob("*.sql")}
        self.assertEqual(left, right)

    def test_package_data_includes_additive_mysql_migrations(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("mysql/migrations/*.sql", pyproject)
        mysql_source = (ROOT / "backend" / "platform" / "database" / "mysql.py").read_text(encoding="utf-8")
        self.assertIn("DEFAULT CURRENT_TIMESTAMP(6)", mysql_source)
        self.assertNotIn("DEFAULT (UTC_TIMESTAMP(6))", mysql_source)


if __name__ == "__main__":
    unittest.main()
