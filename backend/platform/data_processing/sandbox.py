from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PythonVisualizationResult:
    script: str
    artifact: dict[str, Any]


@dataclass(frozen=True)
class PythonDataProcessingResult:
    script: str
    rows: list[dict[str, Any]]
    quality: dict[str, Any]


class PythonSandbox:
    """Controlled local boundary for generated visualization scripts.

    Production deployments should replace this with a containerized worker.
    The local runner intentionally supports only a small declaration-style
    function so the architecture can carry SQL -> rows -> Python chart artifact
    without exposing arbitrary Python execution.
    """

    blocked_terms = (
        "import ",
        "__",
        "subprocess",
        "open(",
        "exec(",
        "eval(",
        "compile(",
        "globals(",
        "locals(",
        "getattr(",
        "setattr(",
        "delattr(",
        "input(",
    )
    allowed_attribute_calls = {"append", "get", "items", "keys", "values"}
    safe_builtins = {
        "abs": abs,
        "all": all,
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
    max_code_chars = 8_000
    max_rows = 2_000
    max_artifact_bytes = 200_000

    def validate_code(self, code: str) -> None:
        if len(code) > self.max_code_chars:
            raise ValueError(f"Visualization script exceeds {self.max_code_chars} characters.")
        lowered = code.lower()
        for term in self.blocked_terms:
            if term in lowered:
                raise ValueError(f"Unsafe Python code term: {term}")
        tree = ast.parse(code, mode="exec")
        _ChartScriptValidator().visit(tree)
        function_names = [
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        ]
        if function_names != ["build_chart"]:
            raise ValueError("Visualization script must define exactly one build_chart function.")

    def validate_processing_code(self, code: str) -> None:
        if len(code) > self.max_code_chars:
            raise ValueError(f"Data-processing script exceeds {self.max_code_chars} characters.")
        lowered = code.lower()
        for term in self.blocked_terms:
            if term in lowered:
                raise ValueError(f"Unsafe Python code term: {term}")
        tree = ast.parse(code, mode="exec")
        _DataProcessingScriptValidator().visit(tree)
        function_names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
        if function_names != ["process_data"]:
            raise ValueError("Data-processing script must define exactly one process_data function.")

    def process_data(
        self,
        code: str,
        data: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> PythonDataProcessingResult:
        if len(data) > self.max_rows:
            raise ValueError(f"Data-processing input exceeds {self.max_rows} rows.")
        self.validate_processing_code(code)
        namespace: dict[str, Any] = {"__builtins__": self.safe_builtins}
        exec(compile(code, "<generated_data_processing>", "exec"), namespace, namespace)
        process_data = namespace.get("process_data")
        if not callable(process_data):
            raise ValueError("Data-processing script did not expose process_data.")
        result = process_data([dict(row) for row in data], dict(context))
        if not isinstance(result, dict) or not isinstance(result.get("rows"), list):
            raise ValueError("Data-processing script must return an object containing rows.")
        rows = result["rows"]
        if len(rows) > self.max_rows or any(not isinstance(row, dict) for row in rows):
            raise ValueError("Data-processing result contains invalid rows.")
        safe_rows = json.loads(json.dumps(rows, ensure_ascii=False))
        quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
        safe_quality = _json_safe_artifact(quality)
        payload_size = len(json.dumps({"rows": safe_rows, "quality": safe_quality}, ensure_ascii=False).encode("utf-8"))
        if payload_size > self.max_artifact_bytes:
            raise ValueError(f"Data-processing result exceeds {self.max_artifact_bytes} bytes.")
        return PythonDataProcessingResult(script=code, rows=safe_rows, quality=safe_quality)

    def render_chart(
        self,
        code: str,
        data: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> PythonVisualizationResult:
        if len(data) > self.max_rows:
            raise ValueError(f"Visualization input exceeds {self.max_rows} rows.")
        self.validate_code(code)
        namespace: dict[str, Any] = {"__builtins__": self.safe_builtins}
        exec(compile(code, "<generated_visualization>", "exec"), namespace, namespace)
        build_chart = namespace.get("build_chart")
        if not callable(build_chart):
            raise ValueError("Visualization script did not expose build_chart.")
        artifact = build_chart([dict(row) for row in data], dict(context))
        if not isinstance(artifact, dict):
            raise ValueError("Visualization script must return a chart artifact object.")
        safe_artifact = _json_safe_artifact(artifact)
        artifact_size = len(json.dumps(safe_artifact, ensure_ascii=False).encode("utf-8"))
        if artifact_size > self.max_artifact_bytes:
            raise ValueError(f"Visualization artifact exceeds {self.max_artifact_bytes} bytes.")
        return PythonVisualizationResult(
            script=code,
            artifact=safe_artifact,
        )


class _ChartScriptValidator(ast.NodeVisitor):
    forbidden_nodes = (
        ast.AsyncFunctionDef,
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
    )

    def visit(self, node: ast.AST) -> Any:
        if isinstance(node, self.forbidden_nodes):
            raise ValueError(f"Unsupported visualization script node: {type(node).__name__}")
        return super().visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        if node.attr not in PythonSandbox.allowed_attribute_calls:
            raise ValueError(f"Unsupported visualization script attribute: {node.attr}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> Any:
        if isinstance(node.func, ast.Name) and node.func.id not in PythonSandbox.safe_builtins:
            raise ValueError(f"Unsupported visualization script call: {node.func.id}")
        if isinstance(node.func, ast.Attribute) and node.func.attr not in PythonSandbox.allowed_attribute_calls:
            raise ValueError(f"Unsupported visualization script method: {node.func.attr}")
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        if node.name != "build_chart":
            raise ValueError("Visualization script must define build_chart.")
        if node.decorator_list:
            raise ValueError("Visualization script decorators are not supported.")
        args = node.args
        positional_args = [arg.arg for arg in args.args]
        if (
            positional_args != ["data", "context"]
            or args.vararg is not None
            or args.kwarg is not None
            or args.kwonlyargs
            or args.defaults
            or args.kw_defaults
        ):
            raise ValueError("build_chart must accept exactly data and context.")
        self.generic_visit(node)


class _DataProcessingScriptValidator(_ChartScriptValidator):
    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        if node.name != "process_data":
            raise ValueError("Data-processing script must define process_data.")
        if node.decorator_list:
            raise ValueError("Data-processing script decorators are not supported.")
        args = node.args
        positional_args = [arg.arg for arg in args.args]
        if (
            positional_args != ["data", "context"]
            or args.vararg is not None
            or args.kwarg is not None
            or args.kwonlyargs
            or args.defaults
            or args.kw_defaults
        ):
            raise ValueError("process_data must accept exactly data and context.")
        self.generic_visit(node)


def _json_safe_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(json.dumps(artifact, ensure_ascii=False))
    except TypeError as exc:
        raise ValueError(f"Visualization artifact must be JSON serializable: {exc}") from exc
