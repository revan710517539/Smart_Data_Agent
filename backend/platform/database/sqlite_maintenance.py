from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class SQLiteMaintenanceResult:
    database_path: str
    integrity: str
    page_count: int
    freelist_count: int
    backup_path: str = ""


def inspect_sqlite_database(db_path: str | Path) -> SQLiteMaintenanceResult:
    path = Path(db_path).resolve()
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        return SQLiteMaintenanceResult(
            database_path=str(path),
            integrity=integrity,
            page_count=int(connection.execute("PRAGMA page_count").fetchone()[0]),
            freelist_count=int(connection.execute("PRAGMA freelist_count").fetchone()[0]),
        )
    finally:
        connection.close()


def backup_sqlite_database(db_path: str | Path, backup_path: str | Path) -> SQLiteMaintenanceResult:
    source_path = Path(db_path).resolve()
    target_path = Path(backup_path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = target_path.with_suffix(target_path.suffix + f".{os.getpid()}.tmp")
    source = sqlite3.connect(str(source_path), timeout=30)
    destination = sqlite3.connect(str(temporary), timeout=30)
    try:
        source.execute("PRAGMA busy_timeout = 30000")
        source.execute("PRAGMA wal_checkpoint(PASSIVE)")
        source.backup(destination, pages=256, sleep=0.01)
        destination.commit()
        integrity = str(destination.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise RuntimeError("sqlite_backup_integrity_failed")
        page_count = int(destination.execute("PRAGMA page_count").fetchone()[0])
        freelist_count = int(destination.execute("PRAGMA freelist_count").fetchone()[0])
    finally:
        destination.close()
        source.close()
    os.replace(temporary, target_path)
    return SQLiteMaintenanceResult(
        database_path=str(source_path),
        integrity="ok",
        page_count=page_count,
        freelist_count=freelist_count,
        backup_path=str(target_path),
    )


def vacuum_sqlite_database(db_path: str | Path) -> SQLiteMaintenanceResult:
    path = Path(db_path).resolve()
    connection = sqlite3.connect(str(path), timeout=30)
    try:
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("VACUUM")
        connection.execute("PRAGMA optimize")
    finally:
        connection.close()
    return inspect_sqlite_database(path)


def default_backup_name(db_path: str | Path, backup_dir: str | Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    source = Path(db_path)
    return Path(backup_dir) / f"{source.stem}-{stamp}.sqlite"
