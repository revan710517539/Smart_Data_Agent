from __future__ import annotations

import queue
import threading
from typing import Any, Callable


class DBAPIConnectionProxy:
    def __init__(self, pool: "DBAPIConnectionPool", connection: Any) -> None:
        self._pool = pool
        self._connection = connection
        self._closed = False

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> Any:
        cursor = self._connection.cursor()
        cursor.execute(sql, parameters)
        return DBAPICursorProxy(cursor)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._pool.release(self._connection)


class DBAPICursorProxy:
    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def fetchall(self):
        try:
            return self._cursor.fetchall()
        finally:
            self.close()

    def fetchone(self):
        try:
            return self._cursor.fetchone()
        finally:
            self.close()

    def close(self) -> None:
        close = getattr(self._cursor, "close", None)
        if callable(close):
            close()


class DBAPIConnectionPool:
    def __init__(
        self,
        factory: Callable[[], Any],
        *,
        min_size: int = 1,
        max_size: int = 10,
        timeout_seconds: float = 10,
    ) -> None:
        if min_size < 0 or max_size < max(1, min_size) or max_size > 100:
            raise ValueError("dbapi_pool_size_invalid")
        self.factory = factory
        self.min_size = min_size
        self.max_size = max_size
        self.timeout_seconds = timeout_seconds
        self._available: queue.LifoQueue[Any] = queue.LifoQueue(maxsize=max_size)
        self._lock = threading.Lock()
        self._created = 0
        self._closed = False
        for _ in range(min_size):
            self._available.put(self._create())

    def connection(self) -> DBAPIConnectionProxy:
        if self._closed:
            raise RuntimeError("dbapi_pool_closed")
        try:
            connection = self._available.get_nowait()
        except queue.Empty:
            with self._lock:
                if self._created < self.max_size:
                    connection = self._create()
                else:
                    connection = None
            if connection is None:
                try:
                    connection = self._available.get(timeout=self.timeout_seconds)
                except queue.Empty as exc:
                    raise TimeoutError("dbapi_pool_timeout") from exc
        return DBAPIConnectionProxy(self, connection)

    def release(self, connection: Any) -> None:
        if self._closed:
            _close_connection(connection)
            return
        rollback = getattr(connection, "rollback", None)
        if callable(rollback):
            try:
                rollback()
            except Exception:
                _close_connection(connection)
                with self._lock:
                    self._created = max(0, self._created - 1)
                return
        try:
            self._available.put_nowait(connection)
        except queue.Full:
            _close_connection(connection)
            with self._lock:
                self._created = max(0, self._created - 1)

    def close(self) -> None:
        self._closed = True
        while True:
            try:
                connection = self._available.get_nowait()
            except queue.Empty:
                break
            _close_connection(connection)
        with self._lock:
            self._created = 0

    def _create(self) -> Any:
        connection = self.factory()
        self._created += 1
        return connection


def _close_connection(connection: Any) -> None:
    close = getattr(connection, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
