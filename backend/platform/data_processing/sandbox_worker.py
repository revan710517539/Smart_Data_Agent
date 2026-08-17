from __future__ import annotations

import json
import resource
import sys
from typing import Any


SAFE_BUILTINS = {
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


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (256_000, 256_000))
    if hasattr(resource, "RLIMIT_AS"):
        try:
            resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        except (OSError, ValueError):
            pass
    resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))


def main() -> int:
    _limits()
    request = json.loads(sys.stdin.buffer.read(2_000_000).decode("utf-8"))
    function_name = str(request["function"])
    namespace: dict[str, Any] = {"__builtins__": SAFE_BUILTINS}
    exec(compile(str(request["code"]), "<generated_analysis>", "exec"), namespace, namespace)
    handler = namespace.get(function_name)
    if not callable(handler):
        raise ValueError("sandbox_function_missing")
    result = handler([dict(row) for row in request["data"]], dict(request["context"]))
    response = json.dumps({"ok": True, "result": result}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(response) > int(request["max_output_bytes"]):
        raise ValueError("sandbox_output_too_large")
    sys.stdout.buffer.write(response)
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except BaseException as exc:
        sys.stderr.write(f"{type(exc).__name__}:{str(exc)[:400]}")
        exit_code = 2
    raise SystemExit(exit_code)
