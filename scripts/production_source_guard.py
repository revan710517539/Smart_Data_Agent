#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ZERO_SHA = "0" * 40


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=check)


def resolve_ref(repo: Path, ref: str) -> str:
    completed = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}", check=False)
    if completed.returncode != 0:
        raise SystemExit(f"production_source_guard_ref_invalid: {ref}")
    return completed.stdout.strip()


def changed_protected_files(repo: Path, old_ref: str, new_ref: str, protected: list[str]) -> list[str]:
    completed = git(repo, "diff", "--name-only", old_ref, new_ref, "--", *protected)
    return [line for line in completed.stdout.splitlines() if line]


def choose_from_tty(changed: list[str]) -> str:
    message = (
        "\n生产源码保护提醒：本次上传修改了最近一次上线保护文件：\n  - "
        + "\n  - ".join(changed)
        + "\n\n请选择：\n"
          "  1) 保留 Git/生产基线版本（阻止本次上传，请先恢复这些文件）\n"
          "  2) 保留本地版本（明确批准这些文件随本次上传更新）\n"
          "输入 1 或 2: "
    )
    try:
        with open("/dev/tty", "r+", encoding="utf-8") as tty:
            tty.write(message)
            tty.flush()
            answer = tty.readline().strip()
    except OSError:
        print(message, file=sys.stderr)
        return ""
    return {"1": "keep-git", "2": "keep-local"}.get(answer, "")


def check(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = repo / manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    protected = list(manifest["protected_files"])
    baseline = resolve_ref(repo, manifest["baseline_sha"])
    local = resolve_ref(repo, args.local_ref)
    remote = args.remote_ref
    if remote == ZERO_SHA:
        remote = baseline
    else:
        remote = resolve_ref(repo, remote)
    changed = changed_protected_files(repo, remote, local, protected)
    if not changed:
        print("PRODUCTION_SOURCE_GUARD_OK protected files unchanged")
        return 0

    details = "\n".join(f"  - {item}" for item in changed)
    print(f"PROTECTED_FILES_CHANGED\n{details}", file=sys.stderr)
    choice = args.choice
    if args.non_interactive and choice is None:
        print("production_source_guard_requires_explicit_choice", file=sys.stderr)
        return 3
    if choice is None:
        choice = choose_from_tty(changed)
    if choice == "keep-local":
        print("KEEP_LOCAL_APPROVED protected files may be uploaded")
        return 0
    if choice == "keep-git":
        print(
            "KEEP_GIT_SELECTED: upload blocked. Restore each protected file before retrying, for example:\n"
            f"  git restore --source {remote} -- " + " ".join(changed),
            file=sys.stderr,
        )
        return 4
    print("invalid_or_missing_choice: upload blocked", file=sys.stderr)
    return 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Protect recent production source changes during Git push")
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("check")
    command.add_argument("--repo", default=".")
    command.add_argument("--manifest", default=".release-guard/production-source.json")
    command.add_argument("--remote-ref", required=True)
    command.add_argument("--local-ref", required=True)
    command.add_argument("--choice", choices=("keep-git", "keep-local"))
    command.add_argument("--non-interactive", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "check":
        return check(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
