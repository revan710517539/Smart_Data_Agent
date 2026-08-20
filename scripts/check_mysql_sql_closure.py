#!/usr/bin/env python3
"""Fail closed if MySQL SQL files drift or use MySQL 8.0.18-incompatible datetime defaults."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPO_MYSQL = ROOT / "backend" / "platform" / "database" / "mysql"
IMAGE_MYSQL_PATHS = (
    Path("/app/backend/platform/database/mysql"),
    Path("/usr/local/lib/python3.13/site-packages/backend/platform/database/mysql"),
)
FORBIDDEN_DATETIME_DEFAULT = "DEFAULT (UTC_TIMESTAMP(6))"


def mysql_sql_checksums(root: Path) -> dict[str, str]:
    if not root.is_dir():
        raise FileNotFoundError(str(root))
    checksums: dict[str, str] = {}
    for path in sorted(root.rglob("*.sql")):
        checksums[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return checksums


def assert_mysql_8018_datetime_defaults(root: Path) -> None:
    offenders: list[str] = []
    for path in sorted(root.rglob("*.sql")):
        if FORBIDDEN_DATETIME_DEFAULT in path.read_text(encoding="utf-8"):
            offenders.append(str(path))
    if offenders:
        raise SystemExit(
            "MySQL 8.0.18 rejects DEFAULT (UTC_TIMESTAMP(6)); use CURRENT_TIMESTAMP(6): "
            + ", ".join(offenders)
        )


def assert_generated_mysql_schema_matches_repo() -> None:
    import subprocess

    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_database_schema.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or completed.stdout.strip() or "mysql_schema_generator_drift")


def assert_image_mysql_sql_identical() -> None:
    existing = [path for path in IMAGE_MYSQL_PATHS if path.is_dir()]
    if len(existing) < 2:
        return
    left, right = mysql_sql_checksums(existing[0]), mysql_sql_checksums(existing[1])
    if left != right:
        raise SystemExit(
            "MySQL SQL closure differs between /app and site-packages: "
            f"{sorted(set(left) ^ set(right)) or 'checksum mismatch'}"
        )
    for path in existing:
        assert_mysql_8018_datetime_defaults(path)


def main() -> None:
    assert_mysql_8018_datetime_defaults(REPO_MYSQL)
    assert_generated_mysql_schema_matches_repo()
    repo = mysql_sql_checksums(REPO_MYSQL)
    if not repo:
        raise SystemExit("mysql_sql_files_missing")
    assert_image_mysql_sql_identical()
    print(f"MySQL SQL closure ok ({len(repo)} files)")


if __name__ == "__main__":
    main()
