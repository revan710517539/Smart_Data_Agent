from __future__ import annotations

import argparse
import json

from backend.platform.database.sqlite_maintenance import (
    backup_sqlite_database,
    default_backup_name,
    inspect_sqlite_database,
    vacuum_sqlite_database,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect, backup, or vacuum the local Smart Data Agent SQLite database.")
    parser.add_argument("action", choices=("check", "backup", "vacuum"))
    parser.add_argument("--db", default=".smart_data_agent.sqlite")
    parser.add_argument("--output")
    parser.add_argument("--backup-dir", default="backups")
    args = parser.parse_args()
    if args.action == "check":
        result = inspect_sqlite_database(args.db)
    elif args.action == "vacuum":
        result = vacuum_sqlite_database(args.db)
    else:
        output = args.output or default_backup_name(args.db, args.backup_dir)
        result = backup_sqlite_database(args.db, output)
    print(json.dumps(result.__dict__, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
