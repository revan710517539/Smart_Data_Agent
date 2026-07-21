from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any

import sqlglot
from sqlglot import exp


@dataclass(frozen=True)
class RawTableReference:
    catalog: str
    schema: str
    table: str
    alias: str
    qualified_name: str


@dataclass(frozen=True)
class SQLFieldReference:
    output_name: str
    expression: str
    source_columns: tuple[str, ...] = ()
    aggregate: str = ""


@dataclass(frozen=True)
class SQLJoinReference:
    table: str
    alias: str
    join_type: str
    condition: str


@dataclass(frozen=True)
class SQLDecomposition:
    dialect: str
    statement_type: str
    normalized_sql: str
    query_hash: str
    raw_tables: tuple[RawTableReference, ...]
    fields: tuple[SQLFieldReference, ...]
    joins: tuple[SQLJoinReference, ...]
    ctes: tuple[str, ...]
    filters: tuple[str, ...]
    group_by: tuple[str, ...]
    order_by: tuple[str, ...]
    parameters: tuple[str, ...]
    table_lineage: tuple[dict[str, Any], ...] = ()
    field_lineage: tuple[dict[str, Any], ...] = ()
    confidence: float = 1.0
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SQLDecomposer:
    """AST-only SQL decomposition and read-only validation."""

    dangerous_functions = {"pg_read_file", "pg_ls_dir", "dblink", "sys_eval", "load_file", "sleep", "benchmark"}

    def parse(self, sql: str, dialect: str = "postgres") -> SQLDecomposition:
        source = str(sql or "").strip()
        if not source:
            raise ValueError("sql_required")
        try:
            statements = sqlglot.parse(source, read=dialect or None)
        except sqlglot.errors.ParseError as exc:
            raise ValueError("sql_parse_failed") from exc
        if len(statements) != 1:
            raise ValueError("single_readonly_statement_required")
        statement = statements[0]
        if not isinstance(statement, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
            raise ValueError("readonly_select_or_with_required")
        self._validate_tree(statement)
        normalized_sql = statement.sql(dialect=dialect, pretty=False, normalize=True)
        query_hash = hashlib.sha256(normalized_sql.encode("utf-8")).hexdigest()
        ctes = tuple(sorted({str(node.alias_or_name) for node in statement.find_all(exp.CTE) if node.alias_or_name}))
        cte_keys = {item.casefold() for item in ctes}
        table_items: list[RawTableReference] = []
        seen_tables: set[tuple[str, str]] = set()
        for node in statement.find_all(exp.Table):
            table = str(node.name or "")
            if not table or table.casefold() in cte_keys:
                continue
            catalog = str(node.catalog or "")
            schema = str(node.db or "")
            qualified = ".".join(item for item in (catalog, schema, table) if item)
            alias = str(node.alias_or_name or table)
            identity = (qualified.casefold(), alias.casefold())
            if identity in seen_tables:
                continue
            seen_tables.add(identity)
            table_items.append(RawTableReference(catalog, schema, table, alias, qualified))

        fields: list[SQLFieldReference] = []
        for select in statement.find_all(exp.Select):
            for expression in select.expressions:
                columns = tuple(dict.fromkeys(_column_name(column) for column in expression.find_all(exp.Column)))
                aggregate = next((node.sql_name().upper() for node in expression.walk() if isinstance(node, exp.AggFunc)), "")
                fields.append(
                    SQLFieldReference(
                        output_name=str(expression.alias_or_name or expression.output_name or expression.sql()),
                        expression=expression.sql(dialect=dialect, pretty=False),
                        source_columns=columns,
                        aggregate=aggregate,
                    )
                )

        joins: list[SQLJoinReference] = []
        for join in statement.find_all(exp.Join):
            target = join.this
            target_name = target.sql(dialect=dialect, pretty=False) if target is not None else ""
            alias = str(getattr(target, "alias_or_name", "") or "")
            condition = join.args.get("on")
            joins.append(
                SQLJoinReference(
                    table=target_name,
                    alias=alias,
                    join_type=str(join.args.get("kind") or join.args.get("side") or "inner").lower(),
                    condition=condition.sql(dialect=dialect, pretty=False) if condition is not None else "",
                )
            )

        filters = tuple(node.this.sql(dialect=dialect, pretty=False) for node in statement.find_all(exp.Where))
        group_by = tuple(
            expression.sql(dialect=dialect, pretty=False)
            for node in statement.find_all(exp.Group)
            for expression in node.expressions
        )
        order_by = tuple(
            expression.sql(dialect=dialect, pretty=False)
            for node in statement.find_all(exp.Order)
            for expression in node.expressions
        )
        parameters = tuple(dict.fromkeys(_parameter_name(node) for node in statement.walk() if isinstance(node, (exp.Placeholder, exp.Parameter))))
        table_lineage = tuple(
            {
                "source": item.qualified_name,
                "source_alias": item.alias,
                "target": "topic_table",
                "edge_type": "reads",
            }
            for item in table_items
        )
        field_lineage = tuple(
            {
                "target_field": item.output_name,
                "source_columns": list(item.source_columns),
                "expression": item.expression,
                "aggregate": item.aggregate,
            }
            for item in fields
        )
        warnings: list[str] = []
        if any(column == "*" or column.endswith(".*") for item in fields for column in item.source_columns):
            warnings.append("wildcard_field_lineage_requires_metadata_expansion")
        return SQLDecomposition(
            dialect=dialect,
            statement_type=type(statement).__name__.lower(),
            normalized_sql=normalized_sql,
            query_hash=query_hash,
            raw_tables=tuple(table_items),
            fields=tuple(fields),
            joins=tuple(joins),
            ctes=ctes,
            filters=filters,
            group_by=group_by,
            order_by=order_by,
            parameters=parameters,
            table_lineage=table_lineage,
            field_lineage=field_lineage,
            confidence=1.0 if table_items else 0.75,
            warnings=tuple(warnings),
        )

    def _validate_tree(self, statement: exp.Expression) -> None:
        forbidden_names = (
            "Insert", "Update", "Delete", "Create", "Drop", "Alter", "Merge", "TruncateTable",
            "Command", "Transaction", "Commit", "Rollback", "Grant", "Revoke", "Copy",
        )
        forbidden = tuple(getattr(exp, name) for name in forbidden_names if hasattr(exp, name))
        if forbidden and any(isinstance(node, forbidden) for node in statement.walk()):
            raise ValueError("sql_write_or_command_not_allowed")
        for node in statement.find_all(exp.Func):
            name = str(node.name if isinstance(node, exp.Anonymous) else node.sql_name() or "").casefold()
            if name in self.dangerous_functions:
                raise ValueError(f"dangerous_sql_function_not_allowed:{name}")


def _column_name(column: exp.Column) -> str:
    parts = [str(part) for part in (column.table, column.name) if str(part)]
    return ".".join(parts) or "*"


def _parameter_name(node: exp.Expression) -> str:
    value = str(getattr(node, "name", "") or node.this or node.sql())
    return re.sub(r"^[:@$?]+", "", value) or "?"
