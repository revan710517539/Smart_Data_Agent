from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "production_source_guard.py"
BASELINE = "2c423c0d8ca505d503c7fb6286d7f54357c9b22b"
PROTECTED = {
    "backend/platform/bootstrap.py",
    "backend/platform/metrics/postgresql_store.py",
    "backend/platform/tests/test_bootstrap_metric_seed.py",
}


def run(*args: str, cwd: Path = ROOT, input_text: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        input=input_text,
        capture_output=True,
        text=True,
    )


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def clone_with_guard_files(temp_dir: str) -> Path:
    repo = Path(temp_dir) / "repo"
    git(Path(temp_dir), "clone", "--quiet", str(ROOT), str(repo))
    for relative in (
        ".release-guard/production-source.json",
        ".githooks/pre-push",
        "scripts/production_source_guard.py",
        "scripts/install-production-source-guard.sh",
    ):
        source = ROOT / relative
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return repo


def test_manifest_pins_the_deployed_baseline_and_first_protected_files() -> None:
    manifest = json.loads((ROOT / ".release-guard" / "production-source.json").read_text(encoding="utf-8"))
    assert manifest["baseline_sha"] == BASELINE
    assert set(manifest["protected_files"]) == PROTECTED
    assert manifest["policy"] == "prompt-on-push"


def test_check_allows_push_when_protected_files_are_unchanged() -> None:
    completed = run("check", "--remote-ref", BASELINE, "--local-ref", "HEAD", "--non-interactive")
    assert completed.returncode == 0, completed.stderr
    assert "PRODUCTION_SOURCE_GUARD_OK" in completed.stdout


def test_check_blocks_noninteractive_push_when_a_protected_file_changed() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        repo = clone_with_guard_files(temp_dir)
        git(repo, "config", "user.email", "guard-test@example.invalid")
        git(repo, "config", "user.name", "Guard Test")
        protected = repo / "backend" / "platform" / "bootstrap.py"
        protected.write_text(protected.read_text(encoding="utf-8") + "\n# guard test\n", encoding="utf-8")
        git(repo, "add", str(protected.relative_to(repo)))
        git(repo, "commit", "--quiet", "-m", "test: change protected source")
        completed = run(
            "check", "--manifest", str(repo / ".release-guard" / "production-source.json"),
            "--repo", str(repo), "--remote-ref", BASELINE, "--local-ref", "HEAD", "--non-interactive",
            cwd=repo,
        )
        assert completed.returncode == 3
        assert "PROTECTED_FILES_CHANGED" in completed.stderr
        assert "bootstrap.py" in completed.stderr


def test_explicit_keep_local_choice_allows_push_and_keep_git_choice_blocks() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        repo = clone_with_guard_files(temp_dir)
        git(repo, "config", "user.email", "guard-test@example.invalid")
        git(repo, "config", "user.name", "Guard Test")
        protected = repo / "backend" / "platform" / "bootstrap.py"
        protected.write_text(protected.read_text(encoding="utf-8") + "\n# guard choice test\n", encoding="utf-8")
        git(repo, "add", str(protected.relative_to(repo)))
        git(repo, "commit", "--quiet", "-m", "test: change protected source")
        common = (
            "check", "--manifest", str(repo / ".release-guard" / "production-source.json"),
            "--repo", str(repo), "--remote-ref", BASELINE, "--local-ref", "HEAD",
        )
        keep_local = run(*common, "--choice", "keep-local", cwd=repo)
        assert keep_local.returncode == 0, keep_local.stderr
        assert "KEEP_LOCAL_APPROVED" in keep_local.stdout
        keep_git = run(*common, "--choice", "keep-git", cwd=repo)
        assert keep_git.returncode == 4
        assert "KEEP_GIT_SELECTED" in keep_git.stderr
        assert "git restore --source" in keep_git.stderr


def test_installer_configures_the_versioned_pre_push_hook() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        repo = clone_with_guard_files(temp_dir)
        completed = subprocess.run(
            ["sh", str(repo / "scripts" / "install-production-source-guard.sh")],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        assert git(repo, "config", "--get", "core.hooksPath") == ".githooks"
        hook = repo / ".githooks" / "pre-push"
        assert hook.exists()
        assert "production_source_guard.py" in hook.read_text(encoding="utf-8")


def test_documentation_explains_local_install_sync_and_both_choices() -> None:
    guide = (ROOT / "docs" / "LOCAL_GIT_PRODUCTION_SOURCE_GUARD.md").read_text(encoding="utf-8")
    assert "install-production-source-guard.sh" in guide
    assert "git pull --ff-only origin main" in guide
    assert "保留 Git 版本" in guide
    assert "保留本地版本" in guide
    assert BASELINE in guide
