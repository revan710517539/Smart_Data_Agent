#!/usr/bin/env python3
"""Resolve a canonical, fail-closed MySQL migration baseline for CI."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SystemExit(detail or f"git_command_failed:{' '.join(args)}")
    return completed.stdout.strip()


def _canonical_commit(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")


def resolve_migration_base(repo: Path, candidate_ref: str, head_ref: str) -> str:
    candidate = str(candidate_ref or "").strip()
    head = str(head_ref or "").strip()
    if not candidate:
        raise SystemExit("mysql_migration_base_ref_required")
    if not head:
        raise SystemExit("mysql_migration_head_ref_required")

    canonical_head = _canonical_commit(repo, head)
    if set(candidate) == {"0"}:
        roots = [
            ref
            for ref in _git(repo, "rev-list", "--max-parents=0", canonical_head).splitlines()
            if ref
        ]
        if len(roots) != 1:
            raise SystemExit(f"mysql_migration_initial_base_ambiguous:{len(roots)}")
        candidate = roots[0]

    canonical_candidate = _canonical_commit(repo, candidate)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", canonical_candidate, canonical_head],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode == 1:
        raise SystemExit("mysql_migration_base_not_ancestor")
    if ancestor.returncode != 0:
        raise SystemExit(
            ancestor.stderr.strip()
            or "git_command_failed:merge-base --is-ancestor"
        )
    return canonical_candidate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-ref", required=True)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--repo", type=Path, default=ROOT)
    args = parser.parse_args()
    print(resolve_migration_base(args.repo.resolve(), args.candidate_ref, args.head_ref))


if __name__ == "__main__":
    main()
