#!/usr/bin/env sh
set -eu
exec uv run --frozen python scripts/check_mysql_sql_closure.py
