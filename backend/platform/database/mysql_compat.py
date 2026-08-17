from __future__ import annotations

import re
import hashlib
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator, Sequence

from .mysql import MySQLConnectionPool


class MySQLSQLTranslationError(RuntimeError):
    pass


@dataclass(frozen=True)
class TranslatedSQL:
    sql: str
    params: tuple[Any, ...]
    returning: tuple[str, ...] = ()


class MySQLStoreConnectionPool:
    """Expose the existing Store DB-API contract over a MySQL primary pool."""

    dialect = "mysql"

    def __init__(self, pool: MySQLConnectionPool) -> None:
        self.raw_pool = pool

    @contextmanager
    def connection(self, *args: Any, **kwargs: Any) -> Iterator["MySQLStoreConnection"]:
        del args, kwargs
        with self.raw_pool.connection() as connection:
            try:
                yield MySQLStoreConnection(connection)
            finally:
                # MySQL starts a transaction for plain SELECT statements when
                # autocommit is disabled. Clear any read snapshot before this
                # pooled connection is reused by another request.
                connection.rollback()

    @contextmanager
    def transaction(self) -> Iterator["MySQLStoreConnection"]:
        with self.raw_pool.transaction() as connection:
            yield MySQLStoreConnection(connection)

    def health(self) -> dict[str, Any]:
        return self.raw_pool.health()

    def close(self) -> None:
        self.raw_pool.close()


class MySQLStoreConnection:
    dialect = "mysql"

    def __init__(self, raw: Any) -> None:
        self.raw = raw
        self._advisory_locks: set[str] = set()

    def cursor(self) -> "MySQLStoreCursor":
        return MySQLStoreCursor(self, self.raw.cursor())

    def commit(self) -> None:
        try:
            self.raw.commit()
        finally:
            self._release_advisory_locks()

    def rollback(self) -> None:
        try:
            self.raw.rollback()
        finally:
            self._release_advisory_locks()

    def begin(self) -> None:
        self.raw.begin()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.raw, name)

    def acquire_advisory_lock(self, value: Any) -> bool:
        lock_name = "sda:" + hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:48]
        with self.raw.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK(%s, 30) AS acquired", (lock_name,))
            row = cursor.fetchone() or {}
        acquired = int(_row_value(row, "acquired", 0) or 0) == 1
        if acquired:
            self._advisory_locks.add(lock_name)
        return acquired

    def _release_advisory_locks(self) -> None:
        if not self._advisory_locks:
            return
        locks = tuple(self._advisory_locks)
        self._advisory_locks.clear()
        with self.raw.cursor() as cursor:
            for lock_name in locks:
                cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))


class MySQLStoreCursor:
    def __init__(self, connection: MySQLStoreConnection, raw: Any) -> None:
        self.connection = connection
        self.raw = raw
        self._synthetic_rows: list[Any] | None = None

    def __enter__(self) -> "MySQLStoreCursor":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.close()
        return False

    @property
    def rowcount(self) -> int:
        return int(self.raw.rowcount)

    def close(self) -> None:
        self.raw.close()

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> int:
        original = str(sql)
        values = tuple(params or ())
        if re.fullmatch(
            r"\s*SELECT\s+pg_advisory_xact_lock\s*\(\s*hashtextextended\s*\(\s*%s\s*,\s*0\s*\)\s*\)\s*",
            original,
            flags=re.I | re.S,
        ):
            if len(values) != 1 or not self.connection.acquire_advisory_lock(values[0]):
                raise MySQLSQLTranslationError("mysql_advisory_lock_timeout")
            self._synthetic_rows = [{"pg_advisory_xact_lock": None}]
            return 1
        returning = _returning_columns(original)
        self._synthetic_rows = None
        if returning and original.lstrip().upper().startswith("UPDATE "):
            self._synthetic_rows = self._select_update_returning(original, values, returning)
        translated = translate_postgresql_sql(original, values)
        result = (
            self.raw.execute(translated.sql, translated.params)
            if translated.params
            else self.raw.execute(translated.sql)
        )
        if returning and original.lstrip().upper().startswith("INSERT "):
            self._synthetic_rows = self._select_insert_returning(
                original,
                translated.sql,
                translated.params,
                returning,
            )
        return int(result)

    def executemany(self, sql: str, params: Sequence[Sequence[Any]]) -> int:
        translated_batches = [translate_postgresql_sql(sql, tuple(item)) for item in params]
        if any(item.returning for item in translated_batches):
            raise MySQLSQLTranslationError("mysql_executemany_returning_unsupported")
        if not translated_batches:
            return 0
        statement = translated_batches[0].sql
        if any(item.sql != statement for item in translated_batches):
            raise MySQLSQLTranslationError("mysql_executemany_shape_mismatch")
        return int(self.raw.executemany(statement, [item.params for item in translated_batches]))

    def fetchone(self) -> Any:
        if self._synthetic_rows is not None:
            return self._synthetic_rows.pop(0) if self._synthetic_rows else None
        return self.raw.fetchone()

    def fetchall(self) -> list[Any]:
        if self._synthetic_rows is not None:
            rows = list(self._synthetic_rows)
            self._synthetic_rows.clear()
            return rows
        return list(self.raw.fetchall())

    def _select_update_returning(
        self,
        sql: str,
        params: tuple[Any, ...],
        returning: tuple[str, ...],
    ) -> list[Any]:
        match = re.match(r"\s*UPDATE\s+([A-Za-z_][\w]*)\s+SET\s+", sql, flags=re.I | re.S)
        where_match = re.search(r"\bWHERE\b(.+?)\bRETURNING\b", sql, flags=re.I | re.S)
        if not match or not where_match:
            raise MySQLSQLTranslationError("mysql_update_returning_shape_unsupported")
        before_where = sql[: where_match.start()]
        where_params = params[_placeholder_count(before_where) :]
        where_sql = _translate_base_sql(where_match.group(1).strip())
        select_sql = f"SELECT {', '.join(returning)} FROM {match.group(1)} WHERE {where_sql} FOR UPDATE"
        self.raw.execute(select_sql, where_params)
        return list(self.raw.fetchall())

    def _select_insert_returning(
        self,
        original: str,
        translated_sql: str,
        params: tuple[Any, ...],
        returning: tuple[str, ...],
    ) -> list[Any]:
        shape = _insert_shape(original, params)
        lookup_columns = shape.conflict_columns or tuple(
            column for column in returning if column in shape.values_by_column
        )
        if not lookup_columns:
            lookup_columns = tuple(
                column
                for column in shape.values_by_column
                if column.endswith(("_key", "_code"))
                or column in {"external_subject", "email", "request_id", "event_hash"}
            )[:1]
        if not lookup_columns:
            raise MySQLSQLTranslationError("mysql_insert_returning_lookup_missing")
        if any(column not in shape.values_by_column for column in lookup_columns):
            raise MySQLSQLTranslationError("mysql_insert_returning_lookup_parameter_missing")
        clauses = " AND ".join(f"{column} <=> %s" for column in lookup_columns)
        lookup_params = tuple(shape.values_by_column[column] for column in lookup_columns)
        self.raw.execute(
            f"SELECT {', '.join(returning)} FROM {shape.table} WHERE {clauses} LIMIT 1",
            lookup_params,
        )
        rows = list(self.raw.fetchall())
        if not rows:
            raise MySQLSQLTranslationError("mysql_insert_returning_row_missing")
        return rows


@dataclass(frozen=True)
class _InsertShape:
    table: str
    values_by_column: dict[str, Any]
    conflict_columns: tuple[str, ...]


def translate_postgresql_sql(sql: str, params: tuple[Any, ...] = ()) -> TranslatedSQL:
    statement = str(sql).strip()
    if not statement:
        raise MySQLSQLTranslationError("mysql_sql_empty")
    returning = _returning_columns(statement)
    if returning:
        statement = re.sub(r"\s+RETURNING\s+[A-Za-z0-9_.,\s]+\s*$", "", statement, flags=re.I)
    normalized_input = tuple(_normalize_mysql_parameter(value) for value in params)
    statement, normalized_params = _expand_any_parameters(statement, normalized_input)
    statement = _translate_base_sql(statement)
    statement = _translate_on_conflict(statement)
    _reject_unsupported_sql(statement)
    return TranslatedSQL(statement, normalized_params, returning)


def _translate_base_sql(sql: str) -> str:
    statement = sql
    statement = re.sub(
        r"EXTRACT\s*\(\s*EPOCH\s+FROM\s+([^)]+)\s*\)\s*::\s*bigint",
        r"UNIX_TIMESTAMP(\1)",
        statement,
        flags=re.I,
    )
    statement = re.sub(r"\bto_timestamp\s*\(\s*(%s)\s*\)", r"FROM_UNIXTIME(\1)", statement, flags=re.I)
    statement = re.sub(
        r"jsonb_set\s*\(\s*COALESCE\s*\(\s*capabilities\s*,\s*'\{\}'\s*::\s*jsonb\s*\)\s*,\s*'\{applicationModule\}'\s*,\s*to_jsonb\s*\(\s*''\s*::\s*text\s*\)\s*,\s*true\s*\)",
        "JSON_SET(COALESCE(capabilities, JSON_OBJECT()), '$.applicationModule', '')",
        statement,
        flags=re.I | re.S,
    )
    statement = re.sub(
        r"COALESCE\s*\(\s*\(([^()]+)->>\s*'([^']+)'\)\s*::\s*boolean\s*,\s*false\s*\)",
        r"COALESCE(JSON_EXTRACT(\1, '$.\2') = TRUE, FALSE)",
        statement,
        flags=re.I,
    )
    statement = re.sub(
        r"([A-Za-z_][\w.]*)\s*->>\s*'([^']+)'",
        r"JSON_UNQUOTE(JSON_EXTRACT(\1, '$.\2'))",
        statement,
    )
    statement = re.sub(r"::\s*(?:jsonb|timestamptz|timestamp|uuid|varchar|text|bigint|boolean)(?:\[\])?", "", statement, flags=re.I)
    statement = re.sub(r"\b([A-Za-z_][\w.]*)\s+ILIKE\s+(%s)", r"LOWER(\1) LIKE LOWER(\2)", statement, flags=re.I)
    statement = re.sub(
        r"([A-Za-z_][\w.]*)\s+IS\s+NOT\s+DISTINCT\s+FROM\s+(%s|[A-Za-z_][\w.]*)",
        r"\1 <=> \2",
        statement,
        flags=re.I,
    )
    statement = re.sub(
        r"([A-Za-z_][\w.]*)\s+IS\s+DISTINCT\s+FROM\s+(%s|[A-Za-z_][\w.]*)",
        r"NOT (\1 <=> \2)",
        statement,
        flags=re.I,
    )
    statement = re.sub(r"\b([A-Za-z_][\w.]*)\s+NULLS\s+LAST", r"(\1 IS NULL), \1", statement, flags=re.I)
    statement = re.sub(r"COUNT\(\*\)\s+FILTER\s*\(\s*WHERE\s+([^)]+)\)", r"SUM(CASE WHEN \1 THEN 1 ELSE 0 END)", statement, flags=re.I)
    statement = re.sub(r"\bnow\s*\(\s*\)", "UTC_TIMESTAMP(6)", statement, flags=re.I)
    statement = re.sub(
        r"FOR\s+UPDATE(?:\s+OF\s+[A-Za-z_][\w]*)?\s+SKIP\s+LOCKED\s+LIMIT\s+(%s|\d+)",
        r"LIMIT \1 FOR UPDATE SKIP LOCKED",
        statement,
        flags=re.I,
    )
    return statement


def _translate_on_conflict(sql: str) -> str:
    match = re.search(
        r"\s+ON\s+CONFLICT(?:\s*\((.*?)\))?\s+DO\s+(NOTHING|UPDATE\s+SET\s+.+)$",
        sql,
        flags=re.I | re.S,
    )
    if not match:
        return sql
    prefix = sql[: match.start()].rstrip()
    action = match.group(2).strip()
    insert = re.match(r"\s*INSERT\s+INTO\s+[A-Za-z_][\w]*\s*\((.*?)\)", prefix, flags=re.I | re.S)
    if not insert:
        raise MySQLSQLTranslationError("mysql_on_conflict_insert_shape_unsupported")
    first_column = _split_top_level(insert.group(1))[0].strip()
    if action.upper() == "NOTHING":
        return f"{prefix} ON DUPLICATE KEY UPDATE {first_column} = {first_column}"
    updates = re.sub(r"\bEXCLUDED\.([A-Za-z_][\w]*)", r"VALUES(\1)", action[10:], flags=re.I)
    updates = re.sub(r"\b([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)", r"\1.\2", updates)
    return f"{prefix} ON DUPLICATE KEY UPDATE {updates}"


def _expand_any_parameters(sql: str, params: tuple[Any, ...]) -> tuple[str, tuple[Any, ...]]:
    statement = sql
    values = list(params)
    while True:
        match = re.search(r"([A-Za-z_][\w.]*)\s*=\s*ANY\s*\(\s*%s\s*\)", statement, flags=re.I)
        if not match:
            break
        index = _placeholder_count(statement[: match.start()])
        if index >= len(values) or not isinstance(values[index], (list, tuple, set, frozenset)):
            raise MySQLSQLTranslationError("mysql_any_parameter_array_required")
        items = list(values[index])
        replacement = "0 = 1" if not items else f"{match.group(1)} IN ({', '.join('%s' for _ in items)})"
        statement = statement[: match.start()] + replacement + statement[match.end() :]
        values[index : index + 1] = items
    return statement, tuple(values)


def _returning_columns(sql: str) -> tuple[str, ...]:
    match = re.search(r"\s+RETURNING\s+([A-Za-z0-9_.,\s]+)\s*$", sql, flags=re.I)
    if not match:
        return ()
    columns = tuple(item.strip() for item in match.group(1).split(",") if item.strip())
    if not columns or any(not re.fullmatch(r"[A-Za-z_][\w]*", item) for item in columns):
        raise MySQLSQLTranslationError("mysql_returning_columns_unsupported")
    return columns


def _insert_shape(sql: str, params: tuple[Any, ...]) -> _InsertShape:
    head = re.match(r"\s*INSERT\s+INTO\s+([A-Za-z_][\w]*)\s*", sql, flags=re.I)
    if not head:
        raise MySQLSQLTranslationError("mysql_insert_shape_unsupported")
    columns_text, after_columns = _parenthesized_at(sql, head.end())
    values_keyword = re.match(r"\s*VALUES\s*", sql[after_columns:], flags=re.I)
    if not values_keyword:
        raise MySQLSQLTranslationError("mysql_insert_values_missing")
    values_text, _ = _parenthesized_at(sql, after_columns + values_keyword.end())
    columns = [item.strip() for item in _split_top_level(columns_text)]
    expressions = _split_top_level(values_text)
    if len(columns) != len(expressions):
        raise MySQLSQLTranslationError("mysql_insert_column_value_mismatch")
    values_by_column: dict[str, Any] = {}
    parameter_index = 0
    for column, expression in zip(columns, expressions):
        count = _placeholder_count(expression)
        if count == 1 and expression.strip().lower() in {"%s", "%s::jsonb", "%s::timestamptz", "%s::uuid", "%s::varchar"}:
            values_by_column[column] = params[parameter_index]
        elif count == 0:
            literal = _sql_literal_value(expression)
            if literal is not _UNRESOLVED:
                values_by_column[column] = literal
        parameter_index += count
    conflict = re.search(r"ON\s+CONFLICT\s*\((.*?)\)\s+DO", sql, flags=re.I | re.S)
    conflict_columns: list[str] = []
    if conflict:
        for item in _split_top_level(conflict.group(1)):
            normalized = item.strip()
            if re.fullmatch(r"[A-Za-z_][\w]*", normalized):
                conflict_columns.append(normalized)
    return _InsertShape(head.group(1), values_by_column, tuple(conflict_columns))


def _parenthesized_at(value: str, offset: int) -> tuple[str, int]:
    start = offset
    while start < len(value) and value[start].isspace():
        start += 1
    if start >= len(value) or value[start] != "(":
        raise MySQLSQLTranslationError("mysql_parenthesized_expression_required")
    depth = 0
    quote: str | None = None
    index = start
    while index < len(value):
        character = value[index]
        if quote:
            if character == quote:
                if index + 1 < len(value) and value[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif character in {"'", '"', "`"}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return value[start + 1 : index], index + 1
        index += 1
    raise MySQLSQLTranslationError("mysql_parenthesis_unclosed")


def _split_top_level(value: str) -> list[str]:
    output: list[str] = []
    buffer: list[str] = []
    depth = 0
    case_depth = 0
    quote: str | None = None
    word: list[str] = []

    def flush_word() -> None:
        nonlocal case_depth
        token = "".join(word).upper()
        word.clear()
        if token == "CASE":
            case_depth += 1
        elif token == "END" and case_depth:
            case_depth -= 1

    for character in value:
        if quote:
            buffer.append(character)
            if character == quote:
                quote = None
            continue
        if character.isalnum() or character == "_":
            word.append(character)
            buffer.append(character)
            continue
        flush_word()
        if character in {"'", '"', "`"}:
            quote = character
            buffer.append(character)
        elif character == "(":
            depth += 1
            buffer.append(character)
        elif character == ")":
            depth -= 1
            buffer.append(character)
        elif character == "," and depth == 0 and case_depth == 0:
            output.append("".join(buffer).strip())
            buffer = []
        else:
            buffer.append(character)
    flush_word()
    if buffer:
        output.append("".join(buffer).strip())
    return output


def _placeholder_count(sql: str) -> int:
    return len(re.findall(r"%s", sql))


def _normalize_mysql_parameter(value: Any) -> Any:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
        value,
    ):
        return value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


_UNRESOLVED = object()


def _sql_literal_value(expression: str) -> Any:
    value = expression.strip()
    if re.fullmatch(r"'(?:''|[^'])*'", value):
        return value[1:-1].replace("''", "'")
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    if value.upper() == "NULL":
        return None
    if value.upper() in {"TRUE", "FALSE"}:
        return value.upper() == "TRUE"
    return _UNRESOLVED


def _reject_unsupported_sql(sql: str) -> None:
    forbidden = (
        r"::\s*[A-Za-z_]",
        r"\bON\s+CONFLICT\b",
        r"\bRETURNING\b",
        r"\bILIKE\b",
        r"\bjsonb_set\b",
        r"\bto_jsonb\b",
        r"\bEXTRACT\s*\(\s*EPOCH",
        r"\bFILTER\s*\(\s*WHERE",
        r"\bIS\s+(?:NOT\s+)?DISTINCT\s+FROM\b",
        r"->>",
    )
    if any(re.search(pattern, sql, flags=re.I) for pattern in forbidden):
        raise MySQLSQLTranslationError("mysql_sql_translation_unsupported")


def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        if key in row:
            return row[key]
        return next(iter(row.values()), None)
    try:
        return row[index]
    except (TypeError, IndexError):
        return None
