#!/usr/bin/env python3
"""Validate the pinned, cross-platform release toolchain contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import subprocess


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "configs" / "release" / "toolchain-lock.json"


def _command_version(*args: str) -> str:
    completed = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if completed.returncode != 0:
        raise SystemExit(f"release_toolchain_command_failed:{args[0]}")
    return completed.stdout.strip()


def _load_contract() -> dict:
    contract = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if contract.get("schema_version") != "smart-data-agent-release-toolchain/v1":
        raise SystemExit("release_toolchain_schema_invalid")
    dockerfile = (ROOT / "Dockerfile.release-toolchain").read_text(encoding="utf-8")
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    package_lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    for section in ("node", "python"):
        image = str(contract[section]["image"])
        if "@sha256:" not in image or image not in dockerfile:
            raise SystemExit(f"release_toolchain_base_image_not_pinned:{section}")
    for apt_setting in (
        'Acquire::Retries "5";',
        'Acquire::Queue-Mode "access";',
        'Acquire::http::Timeout "30";',
        'Acquire::https::Timeout "30";',
    ):
        if apt_setting not in dockerfile:
            raise SystemExit("release_toolchain_apt_retry_contract_missing")
    if "URIs: https://deb.debian.org" not in dockerfile:
        raise SystemExit("release_toolchain_apt_https_contract_missing")
    if 'require("playwright-core/browsers.json")' in dockerfile:
        raise SystemExit("release_toolchain_private_browser_manifest_import_forbidden")
    if 'path.join(root,"browsers.json")' not in dockerfile:
        raise SystemExit("release_toolchain_browser_manifest_resolution_missing")
    playwright_version = str(contract["browser"]["playwright_version"])
    if package.get("devDependencies", {}).get("playwright") != playwright_version:
        raise SystemExit("release_toolchain_playwright_package_mismatch")
    if package_lock.get("packages", {}).get("node_modules/playwright", {}).get("version") != playwright_version:
        raise SystemExit("release_toolchain_playwright_lock_mismatch")
    return contract


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-only", action="store_true")
    args = parser.parse_args()
    contract = _load_contract()
    result: dict[str, object] = {"status": "passed", "contract": contract}
    if not args.contract_only:
        actual = {
            "node": _command_version("node", "--version").removeprefix("v"),
            "npm": _command_version("npm", "--version"),
            "python": platform.python_version(),
            "uv": _command_version("uv", "--version").split()[-1],
        }
        expected = {
            "node": str(contract["node"]["version"]),
            "npm": str(contract["node"]["npm_version"]),
            "python": str(contract["python"]["version"]),
            "uv": str(contract["python"]["uv_version"]),
        }
        if actual != expected:
            raise SystemExit(f"release_toolchain_version_mismatch:expected={expected}:actual={actual}")
        result["actual"] = actual
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
