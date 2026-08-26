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
    release_gate = _read("scripts/release-gate.sh") + _read("scripts/release-gate-in-toolchain.sh")
    production_verify = _read("scripts/verify-production-release.sh") + _read("scripts/verify-production-release-in-toolchain.sh")
    ci = _read(".github/workflows/ci.yml")
    compose = _read("docker-compose.server.yml")
    server_development = _read("scripts/server-development-container.sh")
    server_development_env = _read(".env.server-development.example")
    browser_e2e = _read("scripts/production-auth-browser-e2e.mjs")
    required_standard_markers = (
        "sda-production-development/v1",
        "MySQL 8.0.18",
        "DATA_CRAWLER_SHARED_VOLUME",
        "DATA_CRAWLER_MOUNT_TYPE",
        "DATA_CRAWLER_MOUNT_SOURCE",
        "smart-data-crawler-manifest/v1",
        "migration append-only",
        "canonical tenant ID",
        "真实浏览器",
        "SHA256SUMS",
        "SMART_DATA_AGENT_TARGET_PLATFORM",
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
    require("Dockerfile.release-toolchain" in release_gate, "pinned_release_toolchain_entry")
    require(
        'test "$scope" != candidate || test -n "$toolchain_image"' in release_gate
        and "candidate release requires SMART_DATA_AGENT_TOOLCHAIN_IMAGE" in release_gate,
        "candidate_requires_prebuilt_immutable_toolchain",
    )
    require(
        "SMART_DATA_AGENT_TOOLCHAIN_IMAGE=registry.example.com/sda-release-toolchain@sha256:"
        in _read("docs/server_mysql_deployment.md"),
        "candidate_runbook_immutable_toolchain",
    )
    require("release_gate_evidence.py" in release_gate, "machine_readable_release_gate_evidence")
    require("release_cache_manifest.py verify" in release_gate, "validated_release_dependency_cache")
    require("deployment_identity.py candidate" in release_gate, "candidate_identity_receipt")
    require("deployment_identity.py production" in production_verify, "production_identity_receipt")
    require("pre_cutover_snapshot.py verify" in production_verify, "rollback_image_receipt")
    for script in (release_gate, production_verify, _read("scripts/capture-pre-cutover.sh")):
        require("SMART_DATA_AGENT_TARGET_PLATFORM" in script, "release_target_platform_required")
        require('--platform "$target_platform"' in script, "release_target_platform_forwarded")
    require("deployment_identity_candidate_production_platform_mismatch" in _read("scripts/deployment_identity.py"), "deployment_platform_identity_match")
    require("SMART_DATA_AGENT_EXPECTED_SHA" in _read("scripts/candidate-smoke.sh"), "candidate_exact_sha")
    require(
        "source: data-crawler-shared" in compose
        and "target: /app/data" in compose
        and "read_only: true" in compose
        and "external: true" in compose
        and "DATA_CRAWLER_MOUNT_SOURCE" in compose,
        "compose_crawler_external_volume_read_only",
    )
    require('SMART_DATA_AGENT_AUTO_MIGRATE: "false"' in compose, "compose_no_auto_migrate")
    require(
        "resolve_data_crawler_mount_contract true" in server_development
        and "SMART_DATA_AGENT_DB_BACKUP_RECEIPT" in server_development
        and "create-candidate" in server_development,
        "direct_development_server_contract",
    )
    require(
        "SMART_DATA_AGENT_ENV=development" in server_development_env
        and "SMART_DATA_AGENT_AUTH_MODE=development" in server_development_env
        and "SMART_DATA_AGENT_EMBEDDED_WORKER=true" in server_development_env
        and "SMART_DATA_AGENT_AUTO_MIGRATE=false" in server_development_env,
        "direct_development_runtime_profile",
    )
    release_section = standard.split("## 8. 标准发布门禁", 1)[1].split("## 9.", 1)[0]
    require(
        "SMART_DATA_AGENT_RELEASE_SCOPE=candidate" in release_section
        and "SMART_DATA_AGENT_TARGET_PLATFORM=linux/amd64" in release_section
        and "./scripts/release-gate.sh <40位SHA>" in release_section,
        "standard_single_candidate_gate_entry",
    )
    for internal_script in (
        "./scripts/check-mysql-closure.sh",
        "./scripts/build-image.sh",
        "./scripts/candidate-smoke.sh",
        "./scripts/auth-e2e.sh",
        "./scripts/data-crawler-contract-smoke.sh",
    ):
        require(internal_script not in release_section, f"standard_no_selective_gate:{internal_script}")
    require("/api/data-assets?refresh=1" in browser_e2e, "browser_analysis_forced_catalog_refresh")
    require("historical-e2e-stale-id" in browser_e2e, "browser_analysis_historical_reference")
    require("analysis_e2e_result_rows_missing" in browser_e2e, "browser_analysis_nonempty_result")
    require(STANDARD.is_file(), "standard_file")
    result = {"status": "passed" if not errors else "failed", "checks": len(checks), "errors": errors}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
