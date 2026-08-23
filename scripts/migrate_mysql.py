#!/usr/bin/env python3
"""Apply the append-only MySQL schema as an explicit release job."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.platform.database import apply_mysql_schema  # noqa: E402
from backend.platform.database.mysql import MYSQL_SCHEMA_PATH  # noqa: E402
from scripts.check_mysql_sql_closure import (  # noqa: E402
    assert_generated_mysql_schema_matches_repo,
    assert_mysql_8018_datetime_defaults,
    assert_versioned_checksum_manifest,
)


def main() -> None:
    database_url = os.getenv("SMART_DATA_AGENT_DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("SMART_DATA_AGENT_DATABASE_URL is required")
    assert_mysql_8018_datetime_defaults(MYSQL_SCHEMA_PATH.parent)
    assert_generated_mysql_schema_matches_repo()
    assert_versioned_checksum_manifest()
    result = apply_mysql_schema(database_url)
    print(json.dumps({
        "status": "passed",
        "version": result.version,
        "checksum": result.checksum,
        "applied": result.applied,
        "execution_ms": result.execution_ms,
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        print(json.dumps({
            "status": "failed",
            "error": "mysql_migration_failed",
            "error_type": type(exc).__name__,
            "message": " ".join(str(exc).split())[:500],
        }, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc
