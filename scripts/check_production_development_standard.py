#!/usr/bin/env python3
"""Verify that the repository keeps the production development standard wired into release gates."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "DEVELOPMENT.md"


def _read(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file():
        raise SystemExit(f"production_standard_required_file_missing:{relative}")
    return path.read_text(encoding="utf-8")


def main() -> None:
    standard = _read("DEVELOPMENT.md")
    readme = _read("README.md")
    release_gate = _read("scripts/release-gate.sh")
    ci = _read(".github/workflows/ci.yml")
    compose = _read("docker-compose.server.yml")
    required_standard_markers = (
        "sda-production-development/v1",
        "MySQL 8.0.18",
        "/opt/palywright/examples/data-crawler/runtime-data",
        "smart-data-crawler-manifest/v1",
        "migration append-only",
        "canonical tenant ID",
        "真实浏览器",
        "SHA256SUMS",
        "旧容器停止但保留",
    )
    checks: list[str] = []
    errors: list[str] = []

    def require(condition: bool, code: str) -> None:
        (checks if condition else errors).append(code)

    for marker in required_standard_markers:
        require(marker in standard, f"standard_marker:{marker}")
    require("DEVELOPMENT.md" in readme, "readme_standard_entry")
    require("check_production_development_standard.py" in release_gate, "release_gate_standard_check")
    require("check_mysql_migration_history.py" in release_gate, "release_gate_migration_history")
    require("scripts/release-gate.sh" in ci, "ci_release_gate")
    require("mysql:8.0.18" in ci, "ci_mysql_8018")
    require("SMART_DATA_AGENT_MIGRATION_BASE_REF" in ci, "ci_migration_base_ref")
    require("collect_release_evidence.py" in _read("scripts/build-image.sh"), "release_evidence_pack")
    require("SMART_DATA_AGENT_EXPECTED_SHA" in _read("scripts/candidate-smoke.sh"), "candidate_exact_sha")
    require("/app/data:ro" in compose, "compose_crawler_read_only")
    require('SMART_DATA_AGENT_AUTO_MIGRATE: "false"' in compose, "compose_no_auto_migrate")
    require(STANDARD.is_file(), "standard_file")
    result = {"status": "passed" if not errors else "failed", "checks": len(checks), "errors": errors}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
