#!/usr/bin/env python3
"""Write the completion marker only after a frozen Python sync succeeded."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: write_python_environment_marker.py <marker-path>")
    marker = Path(sys.argv[1]).resolve()
    if marker != ROOT / "artifacts" / "release" / "python-environment.json":
        raise SystemExit("python_environment_marker_path_invalid")
    lock = ROOT / "uv.lock"
    environment_path = Path(sys.prefix).resolve()
    expected_environment_path = (ROOT / ".venv").resolve()
    if environment_path != expected_environment_path:
        raise SystemExit(
            f"python_environment_boundary_mismatch:expected={expected_environment_path}:actual={environment_path}"
        )
    python_executable = Path(sys.executable).absolute()
    if not python_executable.is_relative_to(expected_environment_path):
        raise SystemExit(
            f"python_executable_boundary_mismatch:expected={expected_environment_path}:actual={python_executable}"
        )
    contract_files = ("uv.lock", "pyproject.toml", "requirements.lock", "requirements.runtime.lock")
    payload = {
        "schema_version": "smart-data-agent-python-environment/v1",
        "completed": True,
        "python_version": platform.python_version(),
        "python_executable": str(python_executable),
        "environment_path": str(environment_path),
        "uv_version": subprocess.run(["uv", "--version"], check=True, capture_output=True, text=True).stdout.strip(),
        "uv_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "contract_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in contract_files
        },
        "environment": "frozen-dev",
    }
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(marker)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
