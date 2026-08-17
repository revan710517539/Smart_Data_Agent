from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from backend.platform.database.mysql import MySQLConnectionPool


def sqlite_inventory(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve()
    connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        names = [str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        tables = {}
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            count = int(connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0])
            columns = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({quoted})")]
            tables[name] = {"rows": count, "columns": columns}
        return {"source": str(source), "sha256": _file_hash(source), "tables": tables}
    finally:
        connection.close()


def mysql_inventory(database_url: str) -> dict[str, Any]:
    pool = MySQLConnectionPool(database_url, min_size=1, max_size=1)
    try:
        with pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE() AS database_name")
            database_name = str(_mapping_value(cursor.fetchone(), "database_name"))
            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE() ORDER BY table_name")
            names = [str(_mapping_value(row, "table_name")) for row in cursor.fetchall()]
            tables = {}
            for name in names:
                if not name.replace("_", "").isalnum():
                    raise ValueError("mysql_table_name_invalid")
                cursor.execute(f"SELECT COUNT(*) AS count FROM `{name}`")
                count = int(_mapping_value(cursor.fetchone(), "count"))
                cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s ORDER BY ordinal_position", (name,))
                tables[name] = {"rows": count, "columns": [str(_mapping_value(row, "column_name")) for row in cursor.fetchall()]}
        return {"database": database_name, "tables": tables}
    finally:
        pool.close()


def reconcile(source: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    source_tables = source["tables"]
    target_tables = target["tables"]
    shared = sorted(set(source_tables) & set(target_tables))
    comparisons = []
    for table in shared:
        source_columns = set(source_tables[table]["columns"])
        target_columns = set(target_tables[table]["columns"])
        comparisons.append({
            "table": table,
            "source_rows": source_tables[table]["rows"],
            "target_rows": target_tables[table]["rows"],
            "row_count_matches": source_tables[table]["rows"] == target_tables[table]["rows"],
            "missing_target_columns": sorted(source_columns - target_columns),
        })
    return {
        "source_sha256": source.get("sha256", ""),
        "source_table_count": len(source_tables),
        "target_table_count": len(target_tables),
        "shared_table_count": len(shared),
        "source_only_tables": sorted(set(source_tables) - set(target_tables)),
        "target_only_tables": sorted(set(target_tables) - set(source_tables)),
        "comparisons": comparisons,
        "ready_for_cutover": bool(shared) and all(item["row_count_matches"] and not item["missing_target_columns"] for item in comparisons),
    }


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping_value(row: Any, key: str) -> Any:
    if not isinstance(row, dict):
        return row[0]
    normalized = key.lower()
    for candidate, value in row.items():
        if str(candidate).lower() == normalized:
            return value
    raise KeyError(key)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only SQLite to MySQL migration reconciliation.")
    parser.add_argument("--sqlite", required=True)
    parser.add_argument("--mysql-url", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = reconcile(sqlite_inventory(args.sqlite), mysql_inventory(args.mysql_url))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "ready_for_cutover": report["ready_for_cutover"]}, ensure_ascii=False))
    return 0 if report["ready_for_cutover"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
