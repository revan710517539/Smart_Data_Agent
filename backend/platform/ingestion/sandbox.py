from __future__ import annotations

import ast
import json
from typing import Any


class RestrictedRowTransformSandbox:
    """Small declaration-style Python transform, never a general Python shell."""

    max_code_chars = 16_000
    max_input_rows = 20_000
    max_output_rows = 50_000
    max_output_bytes = 8_000_000
    allowed_attribute_calls = {"get", "items", "keys", "values"}
    safe_builtins = {
        "bool": bool,
        "dict": dict,
        "float": float,
        "int": int,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "round": round,
        "sorted": sorted,
        "str": str,
        "sum": sum,
    }

    def transform(self, code: str, rows: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]:
        if len(rows) > self.max_input_rows:
            raise ValueError("transform_input_row_limit_exceeded")
        self.validate(code)
        namespace: dict[str, Any] = {"__builtins__": self.safe_builtins}
        exec(compile(code, "<acquisition-transform>", "exec"), namespace, namespace)
        transform_rows = namespace.get("transform_rows")
        result = transform_rows([dict(row) for row in rows], dict(context))
        if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
            raise ValueError("transform_output_must_be_list_of_objects")
        if len(result) > self.max_output_rows:
            raise ValueError("transform_output_row_limit_exceeded")
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > self.max_output_bytes:
            raise ValueError("transform_output_size_limit_exceeded")
        return json.loads(encoded.decode("utf-8"))

    def validate(self, code: str) -> None:
        if not code or len(code) > self.max_code_chars:
            raise ValueError("invalid_transform_code_size")
        tree = ast.parse(code, mode="exec")
        _TransformValidator(self).visit(tree)
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        if len(functions) != 1 or functions[0].name != "transform_rows":
            raise ValueError("transform_must_define_exactly_one_transform_rows_function")


class _TransformValidator(ast.NodeVisitor):
    forbidden = (
        ast.AsyncFunctionDef,
        ast.Await,
        ast.ClassDef,
        ast.Delete,
        ast.Global,
        ast.Import,
        ast.ImportFrom,
        ast.Lambda,
        ast.Nonlocal,
        ast.Raise,
        ast.Try,
        ast.While,
        ast.With,
        ast.Yield,
        ast.YieldFrom,
    )

    def __init__(self, sandbox: RestrictedRowTransformSandbox) -> None:
        self.sandbox = sandbox

    def visit(self, node: ast.AST) -> Any:
        if isinstance(node, self.forbidden):
            raise ValueError(f"unsupported_transform_node:{type(node).__name__}")
        return super().visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        if node.attr not in self.sandbox.allowed_attribute_calls:
            raise ValueError(f"unsupported_transform_attribute:{node.attr}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> Any:
        if isinstance(node.func, ast.Name) and node.func.id not in self.sandbox.safe_builtins:
            raise ValueError(f"unsupported_transform_call:{node.func.id}")
        if isinstance(node.func, ast.Attribute) and node.func.attr not in self.sandbox.allowed_attribute_calls:
            raise ValueError(f"unsupported_transform_method:{node.func.attr}")
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        if node.name != "transform_rows" or node.decorator_list:
            raise ValueError("invalid_transform_function")
        args = node.args
        if (
            [arg.arg for arg in args.args] != ["rows", "context"]
            or args.vararg is not None
            or args.kwarg is not None
            or args.kwonlyargs
            or args.defaults
            or args.kw_defaults
        ):
            raise ValueError("transform_rows_must_accept_rows_and_context")
        self.generic_visit(node)
