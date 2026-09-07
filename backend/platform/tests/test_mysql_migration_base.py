from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.resolve_mysql_migration_base import resolve_migration_base


ROOT = Path(__file__).resolve().parents[3]


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _commit(repo: Path, filename: str, contents: str, message: str) -> str:
    (repo / filename).write_text(contents, encoding="utf-8")
    _git(repo, "add", filename)
    _git(
        repo,
        "-c",
        "user.name=Smart Data Agent Tests",
        "-c",
        "user.email=tests@example.invalid",
        "commit",
        "-m",
        message,
    )
    return _git(repo, "rev-parse", "HEAD")


class MysqlMigrationBaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)
        _git(self.repo, "init", "--quiet")
        self.root = _commit(self.repo, "root.txt", "root\n", "root")
        self.head = _commit(self.repo, "head.txt", "head\n", "head")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_explicit_ancestor_is_canonicalized(self) -> None:
        self.assertEqual(resolve_migration_base(self.repo, "HEAD~1", "HEAD"), self.root)

    def test_initial_push_zero_candidate_resolves_unique_root(self) -> None:
        self.assertEqual(resolve_migration_base(self.repo, "0" * 40, self.head), self.root)

    def test_blank_candidate_fails_closed(self) -> None:
        with self.assertRaisesRegex(SystemExit, "mysql_migration_base_ref_required"):
            resolve_migration_base(self.repo, "", self.head)

    def test_unknown_candidate_fails_closed(self) -> None:
        with self.assertRaises(SystemExit):
            resolve_migration_base(self.repo, "missing-ref", self.head)

    def test_non_ancestor_candidate_fails_closed(self) -> None:
        _git(self.repo, "checkout", "--orphan", "unrelated")
        _git(self.repo, "rm", "-rf", ".")
        unrelated = _commit(self.repo, "unrelated.txt", "other\n", "unrelated")
        with self.assertRaisesRegex(SystemExit, "mysql_migration_base_not_ancestor"):
            resolve_migration_base(self.repo, unrelated, self.head)

    def test_initial_push_with_multiple_roots_fails_closed(self) -> None:
        _git(self.repo, "checkout", "--orphan", "second-root")
        _git(self.repo, "rm", "-rf", ".")
        second = _commit(self.repo, "second.txt", "second\n", "second root")
        _git(self.repo, "merge", "--quiet", "--allow-unrelated-histories", "--no-edit", self.head)
        merged = _git(self.repo, "rev-parse", "HEAD")
        self.assertNotEqual(second, merged)
        with self.assertRaisesRegex(SystemExit, "mysql_migration_initial_base_ambiguous:2"):
            resolve_migration_base(self.repo, "0" * 40, merged)

    def test_github_workflow_passes_only_the_resolved_base_to_release_gate(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("SMART_DATA_AGENT_MIGRATION_BASE_CANDIDATE", workflow)
        self.assertIn("scripts/resolve_mysql_migration_base.py", workflow)
        self.assertIn("SMART_DATA_AGENT_MIGRATION_BASE_REF: ${{ steps.migration-base.outputs.base_ref }}", workflow)
        self.assertNotIn(
            "SMART_DATA_AGENT_MIGRATION_BASE_REF: ${{ github.event.pull_request.base.sha || github.event.before }}",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
