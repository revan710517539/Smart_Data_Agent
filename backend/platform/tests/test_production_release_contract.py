from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from contextlib import redirect_stdout
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from scripts.release_identity import frontend_assets_hash
import scripts.release_gate_evidence as release_gate_evidence
from scripts.deployment_identity import assert_capability_compatibility, assert_local_source_closure, deployment_container_evidence, immutable_image_reference_matches
from scripts.data_crawler_mount_contract import MountContractError, normalize_mount_contract
from scripts.release_cache_manifest import create_manifest, verify_manifest
from scripts.pre_cutover_snapshot import build_snapshot
from scripts.mysql_backup_receipt import verify_backup_receipt
from scripts.mysql_migration_receipt import SCHEMA as MIGRATION_RECEIPT_SCHEMA, current_migration_closure, verify_migration_receipt
import scripts.migrate_mysql as migrate_mysql


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


def test_release_gate_rejects_non_sha_before_docker_access() -> None:
    completed = subprocess.run(
        ["sh", str(ROOT / "scripts" / "release-gate.sh"), "short-sha"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert "40-character-git-sha" in completed.stderr


def test_release_gate_accepts_exactly_forty_hex_characters_before_head_check() -> None:
    completed = subprocess.run(
        ["sh", str(ROOT / "scripts" / "release-gate.sh"), "a" * 40],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert "requested SHA is not HEAD" in completed.stderr


def test_typescript_importing_node_contracts_enable_stripping() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["test:client-uuid"] == "node --experimental-strip-types scripts/client-uuid-contract.mjs"
    assert package["scripts"]["test:weekly-page-data-workbench"] == (
        "node --experimental-strip-types scripts/weekly-page-data-workbench-contract.mjs"
    )


def test_release_toolchain_contract_pins_bases_and_browser() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_release_toolchain.py"), "--contract-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert '"status": "passed"' in completed.stdout


def test_candidate_release_requires_an_immutable_prebuilt_toolchain_image() -> None:
    outer = (ROOT / "scripts" / "release-gate.sh").read_text(encoding="utf-8")
    runbook = (ROOT / "docs" / "server_mysql_deployment.md").read_text(encoding="utf-8")
    assert 'test "$scope" != candidate ||' in outer
    assert "candidate release requires SMART_DATA_AGENT_TOOLCHAIN_IMAGE" in outer
    assert "SMART_DATA_AGENT_TOOLCHAIN_IMAGE=registry.example.com/" in runbook
    assert "@sha256:<64位工具链镜像摘要>" in runbook


def test_frontend_asset_identity_is_path_order_independent_and_content_sensitive() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "assets").mkdir()
        (root / "index.html").write_text("one", encoding="utf-8")
        (root / "assets" / "app.js").write_text("two", encoding="utf-8")
        first = frontend_assets_hash(root)
        second = frontend_assets_hash(root)
        assert first == second
        (root / "assets" / "app.js").write_text("changed", encoding="utf-8")
        assert frontend_assets_hash(root) != first


def test_deployment_identity_rejects_non_sha_before_network_access() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "deployment_identity.py"), "candidate", "http://127.0.0.1:1", "short-sha"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "deployment_identity_commit_sha_invalid" in completed.stderr


def test_deployment_identity_requires_explicit_supported_target_platform_before_network_access() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "deployment_identity.py"),
            "candidate",
            "http://127.0.0.1:1",
            "a" * 40,
            "--container",
            "candidate",
            "--data-crawler-volume",
            "crawler-data",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={key: value for key, value in os.environ.items() if key != "SMART_DATA_AGENT_TARGET_PLATFORM"},
    )
    assert completed.returncode != 0
    assert "deployment_identity_target_platform_invalid" in completed.stderr


def test_release_gate_evidence_records_environment_commands_and_result() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        report = root / "release-gate-report.json"
        identity = root / "release-identity.json"
        python_marker = root / "python-environment.json"
        identity.write_text(json.dumps({"commit_sha": "a" * 40}), encoding="utf-8")
        python_marker.write_text(json.dumps({"python_version": "3.13.2"}), encoding="utf-8")
        shared = (
            patch.object(release_gate_evidence, "REPORT", report),
            patch.object(release_gate_evidence, "IDENTITY", identity),
            patch.object(release_gate_evidence, "PYTHON_MARKER", python_marker),
            patch.dict(
                "os.environ",
                {
                    "SMART_DATA_AGENT_RELEASE_OFFLINE": "false",
                    "SMART_DATA_AGENT_TARGET_PLATFORM": "linux/amd64",
                    "SECRET_TOKEN": "must-not-leak",
                },
                clear=True,
            ),
        )
        with shared[0], shared[1], shared[2], shared[3]:
            with patch.object(sys, "argv", ["release_gate_evidence.py", "start", "--commit-sha", "a" * 40, "--scope", "candidate"]):
                release_gate_evidence.main()
            with patch.object(sys, "argv", [
                "release_gate_evidence.py", "step", "--name", "unit_tests",
                "--started-at", "2026-08-26T00:00:00Z", "--completed-at", "2026-08-26T00:00:01Z",
                "--status", "passed", "--exit-code", "0", "--", "npm", "test",
            ]):
                release_gate_evidence.main()
            with patch.object(sys, "argv", ["release_gate_evidence.py", "finish", "--status", "passed"]):
                release_gate_evidence.main()
        payload = json.loads(report.read_text(encoding="utf-8"))
        assert payload["status"] == "passed"
        assert payload["environment"]["target_platform"] == "linux/amd64"
        assert payload["steps"][0]["command"] == ["npm", "test"]
        assert payload["result"] == {"failed_steps": [], "total_steps": 1}
        assert "must-not-leak" not in report.read_text(encoding="utf-8")


def test_release_gate_receipt_binds_candidate_sha_scope_and_exact_toolchain_image() -> None:
    sha = "a" * 40
    toolchain_image_id = "sha256:" + "b" * 64
    with tempfile.TemporaryDirectory() as temp_dir:
        report = Path(temp_dir) / "release-gate-report.json"
        report.write_text(json.dumps({
            "schema_version": "smart-data-agent-release-gate/v3",
            "commit_sha": sha,
            "scope": "candidate",
            "status": "passed",
            "environment": {"toolchain_image_id": toolchain_image_id, "target_platform": "linux/amd64"},
            "identity": {"commit_sha": sha},
            "result": {"failed_steps": [], "total_steps": 1},
        }), encoding="utf-8")
        with patch.object(release_gate_evidence, "REPORT", report):
            release_gate_evidence.verify_receipt(sha, "candidate", toolchain_image_id, "linux/amd64")
            with unittest.TestCase().assertRaisesRegex(SystemExit, "release_gate_receipt_toolchain_image_mismatch"):
                release_gate_evidence.verify_receipt(sha, "candidate", "sha256:" + "c" * 64, "linux/amd64")
            with unittest.TestCase().assertRaisesRegex(SystemExit, "release_gate_receipt_target_platform_mismatch"):
                release_gate_evidence.verify_receipt(sha, "candidate", toolchain_image_id, "linux/arm64")


def test_cutover_scripts_require_clean_worktree_and_forward_exact_toolchain_identity() -> None:
    verify_script = (ROOT / "scripts" / "verify-production-release.sh").read_text(encoding="utf-8")
    verify_inner = (ROOT / "scripts" / "verify-production-release-in-toolchain.sh").read_text(encoding="utf-8")
    capture_script = (ROOT / "scripts" / "capture-pre-cutover.sh").read_text(encoding="utf-8")
    for script in (verify_script, capture_script):
        assert "git status --porcelain --untracked-files=normal" in script
        assert "SMART_DATA_AGENT_RELEASE_TOOLCHAIN_IMAGE_ID=$toolchain_image_id" in script
        assert "SMART_DATA_AGENT_TARGET_PLATFORM" in script
        assert '--platform "$target_platform"' in script
    assert "verify-production-release-in-toolchain.sh" in verify_script
    assert "release_gate_evidence.py verify" in verify_inner
    assert "release_gate_evidence.py verify" in capture_script


def test_single_release_gate_owns_exact_crawler_mount_and_real_analysis_acceptance() -> None:
    outer = (ROOT / "scripts" / "release-gate.sh").read_text(encoding="utf-8")
    inner = (ROOT / "scripts" / "release-gate-in-toolchain.sh").read_text(encoding="utf-8")
    production_outer = (ROOT / "scripts" / "verify-production-release.sh").read_text(encoding="utf-8")
    production_inner = (ROOT / "scripts" / "verify-production-release-in-toolchain.sh").read_text(encoding="utf-8")
    browser = (ROOT / "scripts" / "production-auth-browser-e2e.mjs").read_text(encoding="utf-8")
    standard = (ROOT / "DEVELOPMENT.md").read_text(encoding="utf-8")
    release_section = standard.split("## 8. 标准发布门禁", 1)[1].split("## 9.", 1)[0]
    required_analysis_env = (
        "SMART_DATA_AGENT_ANALYSIS_E2E_TENANT_ID",
        "SMART_DATA_AGENT_ANALYSIS_E2E_RELATIVE_PATH",
        "SMART_DATA_AGENT_ANALYSIS_E2E_CONTENT_HASH",
        "SMART_DATA_AGENT_ANALYSIS_E2E_QUESTION",
    )
    for name in required_analysis_env:
        assert name in outer
        assert name in production_outer
        assert name in browser
    assert "SMART_DATA_AGENT_TARGET_PLATFORM" in outer
    assert '--platform "$target_platform"' in outer
    assert '--platform "$target_platform"' in production_outer
    assert '--platform "$target_platform"' in (ROOT / "scripts" / "build-image.sh").read_text(encoding="utf-8")
    assert ". scripts/data-crawler-mount-contract.sh" in outer
    assert 'resolve_data_crawler_mount_contract true' in outer
    assert '--mount "$data_crawler_mount_spec"' in outer
    assert '--mount "$data_crawler_mount_spec"' in production_outer
    assert "DATA_CRAWLER_MOUNT_TYPE" in inner and "DATA_CRAWLER_MOUNT_SOURCE" in inner
    assert "DATA_CRAWLER_MOUNT_TYPE" in production_inner and "DATA_CRAWLER_MOUNT_SOURCE" in production_inner
    assert "candidate_data_crawler_manifest" in inner and "data-crawler-contract-smoke.sh" in inner
    assert "production_data_crawler_manifest" in production_inner and "data-crawler-contract-smoke.sh" in production_inner
    for endpoint in ("/api/data-assets?refresh=1", "/api/analysis/run-async", "/api/analysis/run-status", "/api/analysis/task"):
        assert endpoint in browser
    assert "historical-e2e-stale-id" in browser
    assert "analysis_e2e_result_rows_missing" in browser
    for forbidden_direct_gate in (
        "./scripts/check-mysql-closure.sh",
        "./scripts/build-image.sh",
        "./scripts/candidate-smoke.sh",
        "./scripts/auth-e2e.sh",
        "./scripts/data-crawler-contract-smoke.sh",
    ):
        assert forbidden_direct_gate not in release_section


def test_candidate_identity_must_match_local_source_closure() -> None:
    identity = {
        "commit_sha": "a" * 40,
        "image_reference": "registry/sda@sha256:" + "b" * 64,
        "source_archive_sha256": "c" * 64,
        "dependency_lock_sha256": "d" * 64,
        "frontend_assets_sha256": "e" * 64,
        "release_toolchain_sha256": "f" * 64,
    }
    local = {key: value for key, value in identity.items() if key != "image_reference"}
    assert_local_source_closure(identity, local)
    local["frontend_assets_sha256"] = "0" * 64
    with unittest.TestCase().assertRaisesRegex(SystemExit, "frontend_assets_sha256"):
        assert_local_source_closure(identity, local)


def test_candidate_and_production_capability_contracts_must_match() -> None:
    candidate = {
        "public_origin": {"configured": True, "enabled": True, "ready": True, "status": "ready", "origin": "https://candidate.example"},
        "data_crawler": {"configured": True, "enabled": True, "ready": True, "status": "ready", "schema_version": "v1", "tenant_count": 2, "file_count": 5, "generated_at": "candidate-time"},
        "asr": {"configured": True, "enabled": False, "ready": True, "status": "disabled", "dependency": "wss"},
    }
    production = {
        **candidate,
        "public_origin": {**candidate["public_origin"], "origin": "https://production.example"},
        "data_crawler": {**candidate["data_crawler"], "generated_at": "production-time"},
    }
    assert_capability_compatibility(candidate, production)
    production["asr"] = {**candidate["asr"], "enabled": True, "status": "enabled"}
    with unittest.TestCase().assertRaisesRegex(SystemExit, "capability_mismatch:asr"):
        assert_capability_compatibility(candidate, production)


def test_release_cache_manifest_binds_locks_inventory_and_file_digests() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_root = Path(temp_dir)
        for directory in ("npm", "uv", "wheelhouse"):
            (cache_root / directory).mkdir()
            (cache_root / directory / f"{directory}.cache").write_text(directory, encoding="utf-8")
        create_manifest(cache_root)
        manifest = cache_root / "release-cache-manifest.json"
        digest = __import__("hashlib").sha256(manifest.read_bytes()).hexdigest()

        result = verify_manifest(cache_root, digest)

        assert result["file_count"] == 3
        (cache_root / "wheelhouse" / "wheelhouse.cache").write_text("tampered", encoding="utf-8")
        with unittest.TestCase().assertRaisesRegex(SystemExit, "release_cache_file_digest_mismatch"):
            verify_manifest(cache_root, digest)


def test_pre_cutover_snapshot_records_bounded_old_image_rollback_identity() -> None:
    old_sha = "1" * 40
    target_sha = "2" * 40
    image_id = "sha256:" + "3" * 64
    payload = build_snapshot(
        base_url="https://production.example/",
        target_release_sha=target_sha,
        candidate={
            "identity": {"commit_sha": target_sha, "image_reference": "registry/sda@sha256:" + "4" * 64},
            "container": {"platform": {"os": "linux", "architecture": "amd64", "variant": "", "platform": "linux/amd64"}},
        },
        health={
            "ready": True,
            "build": {"commit_sha": old_sha},
            "runtime": {"instance_id": "old-runtime"},
            "capabilities": {"asr": {"configured": True, "enabled": False, "ready": True, "status": "disabled"}},
        },
        container={"Id": "container-id", "Image": image_id, "Name": "/sda-production", "State": {"Running": True}, "Config": {"Env": ["SECRET=must-not-leak"]}},
        image={
            "Id": image_id,
            "Os": "linux",
            "Architecture": "amd64",
            "RepoDigests": ["registry/sda@sha256:" + "5" * 64],
            "Config": {"Labels": {"org.opencontainers.image.revision": old_sha, "org.opencontainers.image.source": "https://example/repo", "org.opencontainers.image.created": "2026-08-01T00:00:00Z"}, "Env": ["SECRET=must-not-leak"]},
        },
    )

    serialized = json.dumps(payload)
    assert payload["rollback"]["image_id"] == image_id
    assert payload["rollback"]["platform"]["platform"] == "linux/amd64"
    assert payload["rollback"]["revision"] == old_sha
    assert payload["target_release"]["commit_sha"] == target_sha
    assert "must-not-leak" not in serialized
    with unittest.TestCase().assertRaisesRegex(SystemExit, "candidate_production_platform_mismatch"):
        build_snapshot(
            base_url="https://production.example/",
            target_release_sha=target_sha,
            candidate={
                "identity": {"commit_sha": target_sha, "image_reference": "registry/sda@sha256:" + "4" * 64},
                "container": {"platform": {"os": "linux", "architecture": "arm64", "variant": "", "platform": "linux/arm64"}},
            },
            health={"ready": True, "build": {"commit_sha": old_sha}, "runtime": {"instance_id": "old-runtime"}},
            container={"Id": "container-id", "Image": image_id, "State": {"Running": True}},
            image={
                "Id": image_id,
                "Os": "linux",
                "Architecture": "amd64",
                "RepoDigests": [],
                "Config": {"Labels": {"org.opencontainers.image.revision": old_sha}},
            },
        )


def test_deployment_container_evidence_binds_container_to_exact_image_id_and_digest() -> None:
    sha = "1" * 40
    image_id = "sha256:" + "2" * 64
    digest = "registry/sda@sha256:" + "3" * 64
    volume = "playwright-data-crawler-data"
    read_only_mount = {
        "Type": "volume",
        "Name": volume,
        "Destination": "/app/data",
        "RW": False,
    }
    evidence = deployment_container_evidence(
        {
            "Id": "4" * 64,
            "Image": image_id,
            "Name": "/candidate",
            "State": {"Running": True},
            "Mounts": [read_only_mount],
        },
        {
            "Id": image_id,
            "Os": "linux",
            "Architecture": "amd64",
            "RepoDigests": [digest],
            "Config": {"Labels": {"org.opencontainers.image.revision": sha}},
        },
        commit_sha=sha,
        image_reference=digest,
        data_crawler_mount_type="volume",
        data_crawler_mount_source=volume,
        expected_platform="linux/amd64",
    )
    assert evidence["container_id"] == "4" * 64
    assert evidence["image_id"] == image_id
    assert evidence["platform"] == {
        "os": "linux",
        "architecture": "amd64",
        "variant": "",
        "platform": "linux/amd64",
    }
    assert evidence["data_crawler_mount"] == {
        "type": "volume",
        "source": volume,
        "destination": "/app/data",
        "read_only": True,
    }
    with unittest.TestCase().assertRaisesRegex(SystemExit, "container_digest_mismatch"):
        deployment_container_evidence(
            {"Id": "4" * 64, "Image": image_id, "State": {"Running": True}, "Mounts": [read_only_mount]},
            {
                "Id": image_id,
                "Os": "linux",
                "Architecture": "amd64",
                "RepoDigests": [],
                "Config": {"Labels": {"org.opencontainers.image.revision": sha}},
            },
            commit_sha=sha,
            image_reference=digest,
            data_crawler_mount_type="volume",
            data_crawler_mount_source=volume,
            expected_platform="linux/amd64",
        )
    for bad_mount, expected_error in (
        ({**read_only_mount, "Type": "bind"}, "data_crawler_mount_type_mismatch"),
        ({**read_only_mount, "RW": True}, "data_crawler_mount_not_read_only"),
        ({**read_only_mount, "Name": "different-volume"}, "data_crawler_mount_source_mismatch"),
    ):
        with unittest.TestCase().assertRaisesRegex(SystemExit, expected_error):
            deployment_container_evidence(
                {"Id": "4" * 64, "Image": image_id, "State": {"Running": True}, "Mounts": [bad_mount]},
                {
                    "Id": image_id,
                    "Os": "linux",
                    "Architecture": "amd64",
                    "RepoDigests": [digest],
                    "Config": {"Labels": {"org.opencontainers.image.revision": sha}},
                },
                commit_sha=sha,
                image_reference=digest,
                data_crawler_mount_type="volume",
                data_crawler_mount_source=volume,
                expected_platform="linux/amd64",
            )
    with unittest.TestCase().assertRaisesRegex(SystemExit, "image_platform_mismatch"):
        deployment_container_evidence(
            {"Id": "4" * 64, "Image": image_id, "State": {"Running": True}, "Mounts": [read_only_mount]},
            {
                "Id": image_id,
                "Os": "linux",
                "Architecture": "arm64",
                "RepoDigests": [digest],
                "Config": {"Labels": {"org.opencontainers.image.revision": sha}},
            },
            commit_sha=sha,
            image_reference=digest,
            data_crawler_mount_type="volume",
            data_crawler_mount_source=volume,
            expected_platform="linux/amd64",
        )

    bind_source = "/opt/data-crawler/runtime-data"
    bind_evidence = deployment_container_evidence(
        {
            "Id": "5" * 64,
            "Image": image_id,
            "Name": "/candidate-bind",
            "State": {"Running": True},
            "Mounts": [{"Type": "bind", "Source": bind_source, "Destination": "/app/data", "RW": False}],
        },
        {
            "Id": image_id,
            "Os": "linux",
            "Architecture": "amd64",
            "RepoDigests": [digest],
            "Config": {"Labels": {"org.opencontainers.image.revision": sha}},
        },
        commit_sha=sha,
        image_reference=digest,
        data_crawler_mount_type="bind",
        data_crawler_mount_source=bind_source,
        expected_platform="linux/amd64",
    )
    assert bind_evidence["data_crawler_mount"] == {
        "type": "bind",
        "source": bind_source,
        "destination": "/app/data",
        "read_only": True,
    }


def test_data_crawler_mount_contract_supports_bind_and_legacy_volume_without_ambiguity() -> None:
    assert normalize_mount_contract("bind", "/opt/data-crawler/runtime-data").docker_spec(read_only=True) == (
        "type=bind,src=/opt/data-crawler/runtime-data,dst=/app/data,readonly"
    )
    legacy = normalize_mount_contract(legacy_volume="crawler-data")
    assert legacy.mount_type == "volume"
    assert legacy.source == "crawler-data"
    with unittest.TestCase().assertRaisesRegex(MountContractError, "legacy_volume_conflict"):
        normalize_mount_contract("bind", "/opt/data-crawler/runtime-data", legacy_volume="crawler-data")
    with unittest.TestCase().assertRaisesRegex(MountContractError, "bind_source_not_normalized"):
        normalize_mount_contract("bind", "/opt/data-crawler/../runtime-data")


def test_shell_mount_contract_fails_closed_on_ambiguous_or_non_normalized_sources() -> None:
    script = ROOT / "scripts" / "data-crawler-mount-contract.sh"
    valid = subprocess.run(
        ["bash", "-c", f'. "{script}"; DATA_CRAWLER_MOUNT_TYPE=bind DATA_CRAWLER_MOUNT_SOURCE="$1" resolve_data_crawler_mount_contract true; data_crawler_docker_mount_spec ro', "mount-contract", str(ROOT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert valid.returncode == 0, valid.stderr
    assert valid.stdout.strip() == f"type=bind,src={ROOT},dst=/app/data,readonly"
    ambiguous = subprocess.run(
        ["bash", "-c", f'. "{script}"; DATA_CRAWLER_MOUNT_TYPE=bind DATA_CRAWLER_MOUNT_SOURCE="$1/../other" resolve_data_crawler_mount_contract false', "mount-contract", str(ROOT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert ambiguous.returncode == 2
    assert "must be normalized" in ambiguous.stderr
    conflict = subprocess.run(
        ["bash", "-c", f'. "{script}"; DATA_CRAWLER_MOUNT_TYPE=bind DATA_CRAWLER_MOUNT_SOURCE="$1" DATA_CRAWLER_SHARED_VOLUME=crawler-volume resolve_data_crawler_mount_contract false', "mount-contract", str(ROOT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert conflict.returncode == 2
    assert "conflicts" in conflict.stderr


def test_development_state_volumes_inherit_the_non_root_image_permissions() -> None:
    server_script = (ROOT / "scripts" / "server-development-container.sh").read_text(encoding="utf-8")
    state_mount_function = server_script.split("state_mount_spec()", 1)[1].split("runtime_mount_spec=", 1)[0]
    assert "printf 'type=volume,src=%s,dst=%s'" in state_mount_function
    assert "volume-nocopy" not in state_mount_function.split("printf 'type=volume", 1)[1]
    data_mount_contract = (ROOT / "scripts" / "data-crawler-mount-contract.sh").read_text(encoding="utf-8")
    assert "type=volume,src=%s,dst=/app/data%s,volume-nocopy" in data_mount_contract


def test_development_server_matches_confirmed_tls_and_existing_systemd_controller() -> None:
    deployment_doc = (ROOT / "docs" / "server_mysql_deployment.md").read_text(encoding="utf-8")
    server_script = (ROOT / "scripts" / "server-development-container.sh").read_text(encoding="utf-8")
    server_unit = ROOT / "configs" / "deployment" / "smart-data-agent-docker-mss.service"
    assert "SMART_DATA_AGENT_MYSQL_TLS_MODE" in deployment_doc
    assert "当前 Development 服务器已确认是 `required`" in deployment_doc
    assert "mysql_ca_mount_required=false" in server_script
    assert 'if test "$mysql_ca_mount_required" = true' in server_script
    assert server_unit.is_file()
    assert not (ROOT / "configs" / "deployment" / "smart-data-agent-development.service").exists()
    unit_text = server_unit.read_text(encoding="utf-8")
    assert "docker start --attach ${SMART_DATA_AGENT_CONTAINER_NAME}" in unit_text
    assert "Restart=always" in unit_text


def test_offline_development_identity_accepts_only_the_exact_local_image_id() -> None:
    image_id = "sha256:" + "a" * 64
    assert immutable_image_reference_matches(image_id, image_id=image_id, repo_digests=[])
    assert not immutable_image_reference_matches(
        "sha256:" + "b" * 64,
        image_id=image_id,
        repo_digests=[],
    )
    digest = "registry.example/sda@sha256:" + "c" * 64
    assert immutable_image_reference_matches(digest, image_id=image_id, repo_digests=[digest])


def test_mysql_backup_receipt_binds_exact_backup_and_restore_drill() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        backup = root / "smart-data-agent.sql.gz"
        backup.write_bytes(b"verified-backup")
        digest = __import__("hashlib").sha256(backup.read_bytes()).hexdigest()
        receipt = root / "receipt.json"
        receipt.write_text(json.dumps({
            "schema_version": "smart-data-agent-mysql-backup-receipt/v1",
            "created_at": "2026-08-26T12:00:00Z",
            "source": {"mysql_version": "8.0.18", "database_fingerprint_sha256": "a" * 64},
            "backup": {"file": backup.name, "sha256": digest, "bytes": backup.stat().st_size},
            "restore_test": {"status": "passed", "verified_at": "2026-08-26T12:10:00Z", "target": "isolated"},
        }), encoding="utf-8")
        verified = verify_backup_receipt(
            receipt,
            max_age_seconds=3600,
            now=datetime(2026, 8, 26, 12, 30, tzinfo=timezone.utc),
        )
        assert verified["backup_sha256"] == digest
        with unittest.TestCase().assertRaisesRegex(ValueError, "expired"):
            verify_backup_receipt(
                receipt,
                max_age_seconds=60,
                now=datetime(2026, 8, 26, 12, 30, tzinfo=timezone.utc),
            )
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        payload["restore_test"]["verified_at"] = "2026-08-26T11:59:59Z"
        receipt.write_text(json.dumps(payload), encoding="utf-8")
        with unittest.TestCase().assertRaisesRegex(ValueError, "restore_precedes_backup"):
            verify_backup_receipt(receipt)
        payload["restore_test"]["verified_at"] = "2026-08-26T12:10:00Z"
        receipt.write_text(json.dumps(payload), encoding="utf-8")
        backup.write_bytes(b"tampered")
        with unittest.TestCase().assertRaisesRegex(ValueError, "size_mismatch|hash_mismatch"):
            verify_backup_receipt(receipt)


def test_mysql_migration_receipt_binds_commit_and_current_schema_closure() -> None:
    commit_sha = "a" * 40
    closure = current_migration_closure()
    with tempfile.TemporaryDirectory() as temp_dir:
        receipt = Path(temp_dir) / "migration.json"
        receipt.write_text(json.dumps({
            "schema_version": MIGRATION_RECEIPT_SCHEMA,
            "status": "passed",
            "commit_sha": commit_sha,
            "mysql_target_version": "8.0.18",
            **closure,
            "baseline_applied": False,
            "execution_ms": 14,
        }), encoding="utf-8")
        verified = verify_migration_receipt(receipt, commit_sha)
        assert verified["latest_additive_version"] == closure["latest_additive_version"]
        with unittest.TestCase().assertRaisesRegex(ValueError, "commit_sha_mismatch"):
            verify_migration_receipt(receipt, "b" * 40)
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        payload["latest_additive_version"] = "9999"
        receipt.write_text(json.dumps(payload), encoding="utf-8")
        with unittest.TestCase().assertRaisesRegex(ValueError, "latest_additive_version_mismatch"):
            verify_migration_receipt(receipt, commit_sha)


def test_migration_command_emits_the_exact_revision_receipt_contract() -> None:
    commit_sha = "c" * 40
    output = io.StringIO()
    with (
        patch.dict(os.environ, {
            "SMART_DATA_AGENT_DATABASE_URL": "mysql://redacted.invalid/sda",
            "SMART_DATA_AGENT_COMMIT_SHA": commit_sha,
        }, clear=False),
        patch.object(migrate_mysql, "assert_mysql_8018_datetime_defaults"),
        patch.object(migrate_mysql, "assert_generated_mysql_schema_matches_repo"),
        patch.object(migrate_mysql, "assert_versioned_checksum_manifest"),
        patch.object(migrate_mysql, "apply_mysql_schema", return_value=SimpleNamespace(applied=False, execution_ms=7)),
        redirect_stdout(output),
    ):
        migrate_mysql.main()
    receipt = json.loads(output.getvalue())
    assert receipt["schema_version"] == MIGRATION_RECEIPT_SCHEMA
    assert receipt["commit_sha"] == commit_sha
    assert receipt["latest_additive_version"] == current_migration_closure()["latest_additive_version"]
    assert receipt["mysql_target_version"] == "8.0.18"


class ProductionReleaseContractTest(unittest.TestCase):
    def test_candidate_smoke_fails_before_network_without_exact_sha(self) -> None:
        test_candidate_smoke_fails_before_network_without_exact_sha()

    def test_release_evidence_rejects_non_sha_without_docker_access(self) -> None:
        test_release_evidence_rejects_non_sha_without_docker_access()

    def test_release_gate_rejects_non_sha_before_docker_access(self) -> None:
        test_release_gate_rejects_non_sha_before_docker_access()

    def test_release_gate_accepts_exactly_forty_hex_characters_before_head_check(self) -> None:
        test_release_gate_accepts_exactly_forty_hex_characters_before_head_check()

    def test_typescript_importing_node_contracts_enable_stripping(self) -> None:
        test_typescript_importing_node_contracts_enable_stripping()

    def test_release_toolchain_contract_pins_bases_and_browser(self) -> None:
        test_release_toolchain_contract_pins_bases_and_browser()

    def test_candidate_release_requires_an_immutable_prebuilt_toolchain_image(self) -> None:
        test_candidate_release_requires_an_immutable_prebuilt_toolchain_image()

    def test_frontend_asset_identity_is_path_order_independent_and_content_sensitive(self) -> None:
        test_frontend_asset_identity_is_path_order_independent_and_content_sensitive()

    def test_deployment_identity_rejects_non_sha_before_network_access(self) -> None:
        test_deployment_identity_rejects_non_sha_before_network_access()

    def test_deployment_identity_requires_explicit_supported_target_platform_before_network_access(self) -> None:
        test_deployment_identity_requires_explicit_supported_target_platform_before_network_access()

    def test_release_gate_evidence_records_environment_commands_and_result(self) -> None:
        test_release_gate_evidence_records_environment_commands_and_result()

    def test_release_gate_receipt_binds_candidate_sha_scope_and_exact_toolchain_image(self) -> None:
        test_release_gate_receipt_binds_candidate_sha_scope_and_exact_toolchain_image()

    def test_cutover_scripts_require_clean_worktree_and_forward_exact_toolchain_identity(self) -> None:
        test_cutover_scripts_require_clean_worktree_and_forward_exact_toolchain_identity()

    def test_single_release_gate_owns_exact_crawler_mount_and_real_analysis_acceptance(self) -> None:
        test_single_release_gate_owns_exact_crawler_mount_and_real_analysis_acceptance()

    def test_candidate_identity_must_match_local_source_closure(self) -> None:
        test_candidate_identity_must_match_local_source_closure()

    def test_candidate_and_production_capability_contracts_must_match(self) -> None:
        test_candidate_and_production_capability_contracts_must_match()

    def test_release_cache_manifest_binds_locks_inventory_and_file_digests(self) -> None:
        test_release_cache_manifest_binds_locks_inventory_and_file_digests()

    def test_pre_cutover_snapshot_records_bounded_old_image_rollback_identity(self) -> None:
        test_pre_cutover_snapshot_records_bounded_old_image_rollback_identity()

    def test_deployment_container_evidence_binds_container_to_exact_image_id_and_digest(self) -> None:
        test_deployment_container_evidence_binds_container_to_exact_image_id_and_digest()

    def test_data_crawler_mount_contract_supports_bind_and_legacy_volume_without_ambiguity(self) -> None:
        test_data_crawler_mount_contract_supports_bind_and_legacy_volume_without_ambiguity()

    def test_offline_development_identity_accepts_only_the_exact_local_image_id(self) -> None:
        test_offline_development_identity_accepts_only_the_exact_local_image_id()

    def test_shell_mount_contract_fails_closed_on_ambiguous_or_non_normalized_sources(self) -> None:
        test_shell_mount_contract_fails_closed_on_ambiguous_or_non_normalized_sources()

    def test_development_state_volumes_inherit_the_non_root_image_permissions(self) -> None:
        test_development_state_volumes_inherit_the_non_root_image_permissions()

    def test_development_server_matches_confirmed_tls_and_existing_systemd_controller(self) -> None:
        test_development_server_matches_confirmed_tls_and_existing_systemd_controller()

    def test_mysql_backup_receipt_binds_exact_backup_and_restore_drill(self) -> None:
        test_mysql_backup_receipt_binds_exact_backup_and_restore_drill()

    def test_mysql_migration_receipt_binds_commit_and_current_schema_closure(self) -> None:
        test_mysql_migration_receipt_binds_commit_and_current_schema_closure()

    def test_migration_command_emits_the_exact_revision_receipt_contract(self) -> None:
        test_migration_command_emits_the_exact_revision_receipt_contract()
