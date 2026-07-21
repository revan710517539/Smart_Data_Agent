from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from types import TracebackType
from typing import Any


class LockedSQLiteCursor:
    def __init__(self, cursor: sqlite3.Cursor, lock: threading.RLock) -> None:
        self._cursor = cursor
        self._lock = lock
        self._released = False

    def fetchone(self) -> sqlite3.Row | None:
        try:
            return self._cursor.fetchone()
        finally:
            self._release()

    def fetchall(self) -> list[sqlite3.Row]:
        try:
            return self._cursor.fetchall()
        finally:
            self._release()

    def fetchmany(self, size: int | None = None) -> list[sqlite3.Row]:
        try:
            return self._cursor.fetchmany(size) if size is not None else self._cursor.fetchmany()
        finally:
            self._release()

    def close(self) -> None:
        try:
            self._cursor.close()
        finally:
            self._release()

    def _release(self) -> None:
        if not self._released:
            self._released = True
            self._lock.release()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


class LockedSQLiteConnection:
    """SQLite connection proxy serialized for local threaded API usage."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._lock = threading.RLock()
        self._local = threading.local()

    def _context_depth(self) -> int:
        return int(getattr(self._local, "context_depth", 0))

    @property
    def row_factory(self) -> Any:
        return self._connection.row_factory

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        self._connection.row_factory = value

    def execute(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor | LockedSQLiteCursor:
        if self._context_depth():
            return self._connection.execute(*args, **kwargs)
        self._lock.acquire()
        try:
            cursor = self._connection.execute(*args, **kwargs)
        except BaseException:
            self._lock.release()
            raise
        return LockedSQLiteCursor(cursor, self._lock)

    def executemany(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        with self._lock:
            return self._connection.executemany(*args, **kwargs)

    def executescript(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        with self._lock:
            return self._connection.executescript(*args, **kwargs)

    def commit(self) -> None:
        with self._lock:
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "LockedSQLiteConnection":
        self._lock.acquire()
        self._local.context_depth = self._context_depth() + 1
        self._connection.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        try:
            return self._connection.__exit__(exc_type, exc, traceback)
        finally:
            self._local.context_depth = max(0, self._context_depth() - 1)
            self._lock.release()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


def connect_sqlite(db_path: str | Path) -> LockedSQLiteConnection:
    connection = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.DatabaseError:
        pass
    return LockedSQLiteConnection(connection)
