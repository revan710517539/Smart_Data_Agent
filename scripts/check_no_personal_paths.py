#!/usr/bin/env python3
"""Fail the release when tracked source contains a developer-specific home path."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
MAC_HOME = re.compile("/" + r"Users/([^/\s`'\"<>$]+)(?:/|$)")
LINUX_HOME = re.compile("/" + r"home/([^/\s`'\"<>$]+)(?:/|$)")
WINDOWS_HOME = re.compile(r"(?i)\b[A-Z]:\\Users\\([^\\/\s`'\"<>$]+)(?:\\|$)")
DATA_CRAWLER_CHECKOUT = re.compile(
    r"(?i)/(?:opt|srv|var/lib)/(?:[^/\s`'\"<>$]+/)*(?:playwright|palywright)/"
    r"examples/data-crawler/(?:data|runtime-data)(?:/|:|(?=[\s`'\"<>,;)\]}]|$))"
)
LOOPBACK_SERVICE = re.compile(r"(?i)\b(?:https?|wss?|mysql(?:\+pymysql)?|redis)://(?:127\.0\.0\.1|localhost):([0-9]{1,5})\b")
APPROVED_LOOPBACK_PORTS = frozenset({3306, 3307, 5173, 5174, 8787, 8788, 8795})


def tracked_paths(root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [root / item.decode("utf-8") for item in completed.stdout.split(b"\0") if item]


def scan_paths(root: Path, paths: Iterable[Path]) -> list[dict[str, object]]:
    violations: list[dict[str, object]] = []
    for path in paths:
        try:
            payload = path.read_bytes()
        except OSError:
            continue
        if b"\0" in payload:
            continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue
        normalized = text.replace("\\\\", "\\")
        relative_path = path.relative_to(root).as_posix()
        for line_number, line in enumerate(normalized.splitlines(), 1):
            for code, pattern in (
                ("personal_macos_home", MAC_HOME),
                ("personal_linux_home", LINUX_HOME),
                ("personal_windows_home", WINDOWS_HOME),
            ):
                match = pattern.search(line)
                if match:
                    violations.append(
                        {
                            "code": code,
                            "file": path.relative_to(root).as_posix(),
                            "line": line_number,
                            "account": match.group(1),
                        }
                    )
            if DATA_CRAWLER_CHECKOUT.search(line):
                violations.append(
                    {
                        "code": "personal_data_crawler_checkout",
                        "file": relative_path,
                        "line": line_number,
                    }
                )
            if not _test_or_fixture_path(relative_path):
                for match in LOOPBACK_SERVICE.finditer(line):
                    port = int(match.group(1))
                    if port not in APPROVED_LOOPBACK_PORTS:
                        violations.append(
                            {
                                "code": "personal_loopback_service",
                                "file": relative_path,
                                "line": line_number,
                                "port": port,
                            }
                        )
    return violations


def _test_or_fixture_path(relative_path: str) -> bool:
    path = relative_path.casefold()
    name = Path(path).name
    return (
        "/tests/" in f"/{path}"
        or path.startswith("tests/")
        or any(marker in name for marker in ("smoke", "e2e", "contract"))
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    paths = [path if path.is_absolute() else root / path for path in args.paths] or tracked_paths(root)
    violations = scan_paths(root, paths)
    result = {
        "status": "failed" if violations else "passed",
        "scanned_files": len(paths),
        "violations": violations,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(1 if violations else 0)


if __name__ == "__main__":
    main()
