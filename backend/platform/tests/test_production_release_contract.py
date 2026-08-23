from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]


def test_candidate_smoke_fails_before_network_without_exact_sha() -> None:
    env = dict(os.environ)
    env.pop("SMART_DATA_AGENT_EXPECTED_SHA", None)
    completed = subprocess.run(
        ["sh", str(ROOT / "scripts" / "candidate-smoke.sh"), "http://127.0.0.1:1"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert "SMART_DATA_AGENT_EXPECTED_SHA" in completed.stderr


def test_release_evidence_rejects_non_sha_without_docker_access() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "collect_release_evidence.py"), "image:tag", "short-sha"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "release_evidence_commit_sha_invalid" in completed.stderr
