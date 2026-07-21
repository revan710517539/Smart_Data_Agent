from __future__ import annotations

import re


class ManualSQLValidationError(ValueError):
    pass


def validate_read_only_sql_candidate(value: str) -> str:
    """Validate a candidate before a governed source recompiles it."""

    sql = str(value or "").strip()
    if not sql:
        raise ManualSQLValidationError("manual_sql_empty")
    if len(sql) > 50_000:
        raise ManualSQLValidationError("manual_sql_too_large")
    if "--" in sql or "/*" in sql or "*/" in sql:
        raise ManualSQLValidationError("manual_sql_comments_not_allowed")
    statements = [part.strip() for part in sql.split(";") if part.strip()]
    if len(statements) != 1:
        raise ManualSQLValidationError("manual_sql_single_statement_required")
    sql = statements[0]
    if not re.match(r"^(select|with)\b", sql, re.IGNORECASE):
        raise ManualSQLValidationError("manual_sql_read_only_required")
    forbidden = re.compile(
        r"\b(insert|update|delete|merge|drop|alter|truncate|create|replace|grant|revoke|attach|detach|pragma|copy|call|execute|vacuum|analyze)\b",
        re.IGNORECASE,
    )
    if forbidden.search(sql):
        raise ManualSQLValidationError("manual_sql_forbidden_operation")
    return sql
