#!/usr/bin/env python3
"""Deterministically validate the release-facing server deployment contract."""

from __future__ import annotations

import json
import csv
import hashlib
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []
CHECKS: list[str] = []


def read(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file():
        ERRORS.append(f"missing_file:{relative}")
        return ""
    return path.read_text(encoding="utf-8")


def require(condition: bool, code: str) -> None:
    if condition:
        CHECKS.append(code)
    else:
        ERRORS.append(code)


def requirement_name(value: str) -> str:
    return re.split(r"[<>=!~\[\s]", value.strip(), maxsplit=1)[0].lower().replace("_", "-")


dockerfile = read("Dockerfile")
dockerignore = read(".dockerignore")
env_example = read(".env.example")
production_env_example = read(".env.production.example")
server_development_env_example = read(".env.server-development.example")
dev_compose = read("docker-compose.dev.yml")
server_compose = read("docker-compose.server.yml")
production_lock = read("requirements.lock")
runtime_lock = read("requirements.runtime.lock")
ci = read(".github/workflows/ci.yml")
package_json = read("package.json")
release_gate = read("scripts/release-gate.sh") + read("scripts/release-gate-in-toolchain.sh")
release_gate_outer = read("scripts/release-gate.sh")
release_gate_inner = read("scripts/release-gate-in-toolchain.sh")
readme = read("README.md")
deployment_doc = read("docs/server_mysql_deployment.md")
business_data_manifest_text = read("src/app/data/business-data-manifest.json")
mount_contract_shell = read("scripts/data-crawler-mount-contract.sh")
mount_contract_python = read("scripts/data_crawler_mount_contract.py")
server_development_script = read("scripts/server-development-container.sh")
server_development_env = read(".env.server-development.example")
server_development_unit = read("configs/deployment/smart-data-agent-docker-mss.service")
release_evidence = read("scripts/collect_release_evidence.py")
webhook_helper = read("scripts/configure_forgejo_dokploy_webhook.py")
legacy_personal_crawler_bind = "/opt/" + "palywright/examples/data-crawler/data"

require("SMART_DATA_AGENT_DATA_CRAWLER_ROOT=/app/data" in dockerfile, "dockerfile_data_crawler_root")
require(
    "/app/data" in dockerfile and "/app/Topic_Data" in dockerfile and "/app/runtime" in dockerfile,
    "dockerfile_runtime_directories",
)
require(
    "COPY Origin_Data/mock" not in dockerfile and "COPY Topic_Data" not in dockerfile,
    "dockerfile_no_business_or_test_copy",
)
for pattern in (
    ".git",
    "Origin_Data/*",
    "!Origin_Data/__init__.py",
    "!Origin_Data/metric_dictionary_seed.json",
    "Topic_Data",
    "runtime",
):
    require(pattern in dockerignore.splitlines(), f"dockerignore:{pattern}")
require("src/app/data/*/" in dockerignore.splitlines(), "dockerignore:mounted_business_data")

with (ROOT / "pyproject.toml").open("rb") as handle:
    project = tomllib.load(handle)
direct = {requirement_name(item) for item in project["project"]["dependencies"]}
for lock_name, lock_text in (("production", production_lock), ("runtime", runtime_lock)):
    locked = {
        requirement_name(line)
        for line in lock_text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    for dependency in sorted(direct):
        require(dependency in locked, f"{lock_name}_dependency:{dependency}")

for content, label in ((dev_compose, "dev_compose"), (server_compose, "server_compose")):
    require("SMART_DATA_AGENT_DATA_CRAWLER_ROOT: /app/data" in content, f"{label}_data_root")
    require("SMART_DATA_AGENT_DATA_WAREHOUSE: csv" in content, f"{label}_csv_warehouse")
    require("SMART_DATA_AGENT_DATABASE_URL" in content, f"{label}_mysql_secret_reference")
    require(
        "/app/Origin_Data" not in content and "SMART_DATA_AGENT_CSV_SOURCE_ROOT" not in content,
        f"{label}_no_retired_source",
    )
require("/app/data:ro" in dev_compose, "dev_compose_read_only_data_mount")
require(
    "source: data-crawler-shared" in server_compose
    and "target: /app/data" in server_compose
    and "read_only: true" in server_compose
    and "external: true" in server_compose
    and "DATA_CRAWLER_MOUNT_SOURCE" in server_compose,
    "server_compose_shared_external_crawler_volume",
)
require("SMART_DATA_AGENT_DATA_CRAWLER_HOST_ROOT" not in server_compose, "server_compose_no_crawler_host_bind")
require(
    "DATA_CRAWLER_MOUNT_TYPE" in business_data_manifest_text
    and "DATA_CRAWLER_MOUNT_SOURCE" in business_data_manifest_text
    and legacy_personal_crawler_bind not in business_data_manifest_text,
    "business_data_manifest_shared_crawler_mount",
)
require("runtime-data" not in server_compose, "strict_compose_no_bind_source")
require("/run/secrets/mysql_ca.pem:ro" in server_compose, "server_compose_mysql_ca_read_only")
require(
    "/app/Topic_Data" in server_compose and "/app/runtime" in server_compose,
    "server_compose_persistent_generated_state",
)
require("migration:" in server_compose and "service_completed_successfully" in server_compose, "server_compose_explicit_migration_job")
require("capabilities:" in server_compose and "provision_production_capabilities.py" in server_compose, "server_compose_explicit_capability_job")
require("api:" in server_compose and "worker:" in server_compose, "server_compose_separate_api_worker")
require("SMART_DATA_AGENT_ENV: production" in server_compose, "server_compose_production_environment")
require("SMART_DATA_AGENT_AUTH_MODE: strict" in server_compose, "server_compose_strict_auth")
require('SMART_DATA_AGENT_AUTO_MIGRATE: "false"' in server_compose, "server_compose_no_runtime_migration")
require('SMART_DATA_AGENT_EMBEDDED_WORKER: "false"' in server_compose, "server_compose_external_worker")
require("SMART_DATA_AGENT_CAPABILITY_MODE: verify" in server_compose and "SMART_DATA_AGENT_CAPABILITY_MODE: seed" in server_compose, "server_compose_capability_lifecycle")
require("SMART_DATA_AGENT_WORKER_HEALTH_FILE: /app/runtime/worker-health.json" in server_compose, "server_compose_worker_heartbeat")
require("read_only: true" in server_compose and "no-new-privileges:true" in server_compose, "server_compose_read_only_hardened")
require("SMART_DATA_AGENT_IMAGE:?set an immutable repository@sha256 digest reference" in server_compose, "server_compose_immutable_image")
require(
    "SMART_DATA_AGENT_DEVELOPMENT_LOGIN_PASSWORD" not in server_compose,
    "server_compose_no_development_login",
)

require("SMART_DATA_AGENT_DATA_CRAWLER_ROOT=" in env_example, "env_data_crawler_key")
require("SMART_DATA_AGENT_CSV_SOURCE_ROOT=" not in env_example, "env_no_retired_source_key")
require("SMART_DATA_AGENT_DEVELOPMENT_LOGIN_PASSWORD=" in env_example, "env_login_secret_key")
for key in (
    "SMART_DATA_AGENT_IMAGE=",
    "SMART_DATA_AGENT_PUBLIC_ORIGIN=",
    "SMART_DATA_AGENT_OIDC_ISSUER=",
    "SMART_DATA_AGENT_REDIS_URL=rediss://",
    "SMART_DATA_AGENT_OBJECT_BUCKET=",
    "SMART_DATA_AGENT_KMS_COMMAND=",
):
    require(key in production_env_example, f"production_env:{key}")
require("DATA_CRAWLER_SHARED_VOLUME=" in production_env_example, "production_env:shared_crawler_volume")
require("DATA_CRAWLER_MOUNT_TYPE=volume" in production_env_example, "production_env:crawler_mount_type")
require("DATA_CRAWLER_MOUNT_SOURCE=" in production_env_example, "production_env:crawler_mount_source")
require("SMART_DATA_AGENT_DATA_CRAWLER_HOST_ROOT=" not in production_env_example, "production_env:no_server_host_bind")
for marker in (
    "SMART_DATA_AGENT_ENV=development",
    "SMART_DATA_AGENT_AUTH_MODE=development",
    "SMART_DATA_AGENT_AUTO_MIGRATE=false",
    "SMART_DATA_AGENT_EMBEDDED_WORKER=true",
    "SMART_DATA_AGENT_OBJECT_STORE=local",
    "SMART_DATA_AGENT_DATA_CRAWLER_ROOT=/app/data",
):
    require(marker in server_development_env_example, f"server_development_env:{marker}")

require("image: mysql:8.0.18@sha256:" in ci, "ci_mysql_8018_digest")
require("SMART_DATA_AGENT_TEST_MYSQL_URL" in ci, "ci_mysql_integration_url")
require(
    "SMART_DATA_AGENT_TEST_POSTGRES_URL" not in ci and "image: postgres:" not in ci,
    "ci_no_postgresql_primary",
)
require("scripts/release-gate.sh" in ci, "ci_release_gate")
require(
    "https://xujingbo-jk-git.qifudigitech.com/api/v1" in webhook_helper,
    "webhook_helper_qifu_api",
)
require('"test:frontend-contracts"' in package_json, "package_frontend_contract_suite")
require("npm run test:frontend-contracts" in package_json, "package_full_test_includes_frontend_contracts")
for contract_script in (
    "test:browser-executable",
    "test:context-rail",
    "test:visualization-interaction",
    "test:visualization-workbench",
    "test:visual-report-workbench",
    "test:weekly-page-data-workbench",
    "test:page-data-modal",
    "test:route-performance",
    "test:field-semantics",
    "test:visible-account-name",
    "test:product-consistency",
):
    require(f"npm run {contract_script}" in package_json, f"package_frontend_contract:{contract_script}")
require("check_server_deployment_contract.py" in release_gate, "release_gate_deployment_contract")
require("check_production_capability_pack.py" in release_gate, "release_gate_capability_pack")
require("scripts/build-image.sh" in release_gate, "ci_immutable_image_builder")

for content, label in ((readme, "readme"), (deployment_doc, "deployment_doc")):
    require(
        "SMART_DATA_AGENT_DATA_CRAWLER_ROOT" in content and "/app/data" in content,
        f"{label}_current_source_contract",
    )
    require("scripts/provision_production.py" in content, f"{label}_explicit_empty_database_provision")
    require("DATA_CRAWLER_MOUNT_TYPE" in content, f"{label}_shared_crawler_mount_type")
    require("DATA_CRAWLER_MOUNT_SOURCE" in content, f"{label}_shared_crawler_mount_source")
    require("DATA_CRAWLER_SHARED_VOLUME" in content, f"{label}_strict_compose_volume_compatibility")
    require(legacy_personal_crawler_bind not in content, f"{label}_no_personal_server_host_path")

for script in (
    "scripts/release-gate.sh",
    "scripts/release-gate-in-toolchain.sh",
    "scripts/check-mysql-closure.sh",
    "scripts/build-image.sh",
    "scripts/candidate-smoke.sh",
    "scripts/auth-e2e.sh",
    "scripts/data-crawler-contract-smoke.sh",
    "scripts/collect_release_evidence.py",
    "scripts/release_gate_evidence.py",
    "scripts/release_cache_manifest.py",
    "scripts/verify-production-release.sh",
    "scripts/verify-production-release-in-toolchain.sh",
    "scripts/capture-pre-cutover.sh",
    "scripts/pre_cutover_snapshot.py",
):
    require((ROOT / script).is_file(), f"release_script:{script}")

require("org.opencontainers.image.revision" in dockerfile, "dockerfile_commit_label")
for marker in (
    "com.smartdataagent.source-archive-sha256",
    "com.smartdataagent.dependency-lock-sha256",
    "com.smartdataagent.frontend-assets-sha256",
    "com.smartdataagent.release-toolchain-sha256",
):
    require(marker in dockerfile, f"dockerfile_identity_label:{marker}")
require("Dockerfile.release-toolchain" in read("scripts/release-gate.sh"), "release_gate_pinned_toolchain")
require(
    'test "$scope" != candidate || test -n "$toolchain_image"' in release_gate_outer
    and "candidate release requires SMART_DATA_AGENT_TOOLCHAIN_IMAGE" in release_gate_outer,
    "candidate_gate_requires_prebuilt_toolchain",
)
require(
    "SMART_DATA_AGENT_TOOLCHAIN_IMAGE=registry.example.com/sda-release-toolchain@sha256:" in deployment_doc,
    "deployment_doc_candidate_immutable_toolchain",
)
require("deployment_identity.py" in release_gate, "release_gate_candidate_identity")
require("data-crawler-mount-contract.sh" in release_gate, "release_gate_shared_crawler_mount_contract")
require("DATA_CRAWLER_MOUNT_TYPE" in release_gate, "release_gate_shared_crawler_mount_type")
require("DATA_CRAWLER_MOUNT_SOURCE" in release_gate, "release_gate_shared_crawler_mount_source")
require("--data-crawler-mount-type" in release_gate, "candidate_identity_crawler_mount_type")
require("--data-crawler-mount-source" in release_gate, "candidate_identity_crawler_mount_source")
production_verify_outer = read("scripts/verify-production-release.sh")
production_verify_inner = read("scripts/verify-production-release-in-toolchain.sh")
require("DATA_CRAWLER_MOUNT_TYPE" in production_verify_outer, "production_verify_shared_crawler_mount_type")
require("DATA_CRAWLER_MOUNT_SOURCE" in production_verify_outer, "production_verify_shared_crawler_mount_source")
require("deployment_identity.py" in production_verify_inner, "post_deploy_production_identity")
require("--data-crawler-mount-type" in production_verify_inner, "production_identity_crawler_mount_type")
require("--data-crawler-mount-source" in production_verify_inner, "production_identity_crawler_mount_source")
for content, label in (
    (release_gate_outer, "candidate"),
    (production_verify_outer, "production"),
    (read("scripts/capture-pre-cutover.sh"), "pre_cutover"),
):
    require("SMART_DATA_AGENT_TARGET_PLATFORM" in content, f"{label}_target_platform_required")
    require('--platform "$target_platform"' in content, f"{label}_target_platform_forwarded")
require('--platform "$target_platform"' in read("scripts/build-image.sh"), "application_image_target_platform")
require("SMART_DATA_AGENT_TARGET_PLATFORM=linux/amd64" in deployment_doc, "deployment_doc_target_platform")
deployment_identity = read("scripts/deployment_identity.py")
deployment_mount_contract = deployment_identity + mount_contract_python
for marker in (
    "data_crawler_mount_type_mismatch",
    "data_crawler_mount_source_mismatch",
    "not_read_only",
    "deployment_identity_image_platform_mismatch",
    "deployment_identity_candidate_production_platform_mismatch",
):
    require(marker in deployment_mount_contract, f"deployment_identity:{marker}")
require("pre_cutover_snapshot.py verify" in read("scripts/verify-production-release-in-toolchain.sh"), "post_deploy_rollback_image_verification")
require("release_gate_evidence.py" in release_gate, "release_gate_machine_readable_steps")
require("release_cache_manifest.py verify" in release_gate, "release_gate_validated_dependency_cache")
require("--build-context \"release-cache=$cache_context\"" in read("scripts/build-image.sh"), "application_image_release_cache_context")
require("--network none" in read("scripts/build-image.sh"), "offline_application_image_network_disabled")
require("SMART_DATA_AGENT_COMMIT_SHA=${SMART_DATA_AGENT_COMMIT_SHA}" in dockerfile, "dockerfile_runtime_commit_sha")
require("collect_release_evidence.py" in read("scripts/build-image.sh"), "build_image_release_evidence")
require("SMART_DATA_AGENT_EXPECTED_SHA" in read("scripts/candidate-smoke.sh"), "candidate_exact_sha")
require("check_frontend_delivery.mjs" in dockerfile, "dockerfile_frontend_delivery_gate")

analysis_browser = read("scripts/production-auth-browser-e2e.mjs")
analysis_e2e_env = (
    "SMART_DATA_AGENT_ANALYSIS_E2E_TENANT_ID",
    "SMART_DATA_AGENT_ANALYSIS_E2E_RELATIVE_PATH",
    "SMART_DATA_AGENT_ANALYSIS_E2E_CONTENT_HASH",
    "SMART_DATA_AGENT_ANALYSIS_E2E_QUESTION",
)
for name in analysis_e2e_env:
    require(name in release_gate_outer, f"candidate_analysis_env:{name}")
    require(name in production_verify_outer, f"production_analysis_env:{name}")
    require(name in analysis_browser, f"browser_analysis_env:{name}")
require(
    '--mount "$data_crawler_mount_spec"' in release_gate_outer,
    "candidate_gate_exact_crawler_read_only_mount",
)
require(
    '--mount "$data_crawler_mount_spec"' in production_verify_outer,
    "production_gate_exact_crawler_read_only_mount",
)
require(
    "candidate_data_crawler_manifest" in release_gate_inner
    and "data-crawler-contract-smoke.sh" in release_gate_inner,
    "candidate_gate_crawler_manifest",
)
require(
    "production_data_crawler_manifest" in production_verify_inner
    and "data-crawler-contract-smoke.sh" in production_verify_inner,
    "production_gate_crawler_manifest",
)
for endpoint in (
    "/api/data-assets?refresh=1",
    "/api/analysis/run-async",
    "/api/analysis/run-status",
    "/api/analysis/task",
):
    require(endpoint in analysis_browser, f"browser_real_analysis_endpoint:{endpoint}")
require("historical-e2e-stale-id" in analysis_browser, "browser_historical_asset_rebind")
require("analysis_e2e_result_rows_missing" in analysis_browser, "browser_analysis_nonempty_rows")
require(
    deployment_doc.count("DATA_CRAWLER_MOUNT_TYPE=") >= 2
    and deployment_doc.count("DATA_CRAWLER_MOUNT_SOURCE=") >= 2,
    "deployment_doc_candidate_and_production_exact_crawler_mount",
)

for marker in (
    "resolve_data_crawler_mount_contract true",
    "SMART_DATA_AGENT_ENV=development",
    "SMART_DATA_AGENT_AUTH_MODE=development",
    "SMART_DATA_AGENT_AUTO_MIGRATE=false",
    "SMART_DATA_AGENT_EMBEDDED_WORKER=true",
    "SMART_DATA_AGENT_DB_BACKUP_RECEIPT",
    "SMART_DATA_AGENT_DB_BACKUP_MAX_AGE_SECONDS",
    "exact candidate container already exists",
    "SMART_DATA_AGENT_MYSQL_TLS_MODE must occur exactly once",
    "SMART_DATA_AGENT_DATABASE_URL ssl_mode must match SMART_DATA_AGENT_MYSQL_TLS_MODE",
    "SMART_DATA_AGENT_CORS_ORIGINS must include SMART_DATA_AGENT_PUBLIC_ORIGIN",
    "SMART_DATA_AGENT_AUTH_SECRET must contain at least 32 characters",
):
    require(marker in server_development_script, f"server_development_script:{marker}")
require("bind" in mount_contract_shell and "volume" in mount_contract_shell, "mount_contract_shell_dual_topology")
require("bind" in mount_contract_python and "volume" in mount_contract_python, "mount_contract_python_dual_topology")
require("mysql_backup_receipt_restore_precedes_backup" in read("scripts/mysql_backup_receipt.py"), "mysql_backup_receipt_time_order")
require("mysql_backup_receipt_expired" in read("scripts/mysql_backup_receipt.py"), "mysql_backup_receipt_max_age")
require("mysql_migration_receipt_commit_sha_mismatch" in read("scripts/mysql_migration_receipt.py"), "mysql_migration_receipt_commit_identity")
require("latest_additive_version" in read("scripts/mysql_migration_receipt.py"), "mysql_migration_receipt_schema_closure")
require('verify_migration_receipt "$migration_receipt"' in server_development_script, "server_development_revalidates_migration_receipt")
require("EnvironmentFile=/etc/sysconfig/smart-data-agent" in server_development_unit, "server_development_systemd_env")
require("docker start --attach ${SMART_DATA_AGENT_CONTAINER_NAME}" in server_development_unit, "server_development_systemd_exact_container")
require("Restart=always" in server_development_unit, "server_development_systemd_restart_owner")
require("--restart no" in server_development_script, "server_development_no_dual_restart_owner")
require("mysql80.service" not in server_development_unit, "server_development_no_unconfirmed_mysql_unit")
require("smart-data-agent-docker-mss.service" in deployment_doc, "server_development_reuses_existing_systemd_unit_name")
require("ssl_mode=required" in server_development_env, "server_development_matches_confirmed_mysql_tls_mode")
require("SMART_DATA_AGENT_MYSQL_TLS_MODE=required" in server_development_env, "server_development_explicit_mysql_tls_mode")
require("mysql_ca_mount_required" in server_development_script, "server_development_conditional_mysql_ca_mount")
require(
    "Runtime/Topic volumes intentionally use Docker's first-mount copy-up" in server_development_script
    and "printf 'type=volume,src=%s,dst=%s'" in server_development_script,
    "server_development_state_volume_inherits_app_permissions",
)
for path in (
    ".env.server-development.example",
    "configs/deployment/smart-data-agent-docker-mss.service",
    "scripts/data-crawler-mount-contract.sh",
    "scripts/data_crawler_mount_contract.py",
    "scripts/deployment_identity.py",
    "scripts/mysql_backup_receipt.py",
    "scripts/mysql_migration_receipt.py",
    "scripts/server-development-container.sh",
):
    require(Path(path).name in release_evidence, f"release_evidence_critical:{path}")
for name in analysis_e2e_env:
    require(
        deployment_doc.count(name) >= 2,
        f"deployment_doc_candidate_and_production_analysis:{name}",
    )

try:
    business_data_manifest = json.loads(business_data_manifest_text)
except json.JSONDecodeError:
    business_data_manifest = {}
    ERRORS.append("business_data_manifest_json")
datasets = business_data_manifest.get("datasets") if isinstance(business_data_manifest, dict) else []
require(isinstance(datasets, list) and bool(datasets), "business_data_manifest_nonempty")
relationship_groups: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
for index, item in enumerate(datasets if isinstance(datasets, list) else []):
    label = f"business_data:{index}"
    require(isinstance(item, dict), f"{label}:object")
    if not isinstance(item, dict):
        continue
    relative = str(item.get("path") or "")
    path = (ROOT / relative).resolve()
    require(relative.startswith("src/app/data/") and path.is_relative_to(ROOT / "src/app/data"), f"{label}:scoped_path")
    require(path.is_file(), f"{label}:file")
    if not path.is_file():
        continue
    content = path.read_bytes()
    require(hashlib.sha256(content).hexdigest() == str(item.get("sha256") or ""), f"{label}:sha256")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            headers = tuple(next(reader, []))
            row_count = sum(1 for _ in reader)
    except (OSError, UnicodeError, csv.Error):
        headers = ()
        row_count = -1
        ERRORS.append(f"{label}:csv")
    require(row_count == int(item.get("rows") or -1), f"{label}:rows")
    require(len(headers) == int(item.get("columns") or -1), f"{label}:columns")
    require(not any(re.search(r"姓名|身份证|证件号|手机号|手机号码|客户号|银行卡号|账号|邮箱", header) for header in headers), f"{label}:no_direct_identifier_headers")
    group = str(item.get("relationship_group") or "").strip()
    if group:
        relationship_groups.setdefault(group, []).append((str(item.get("institution") or ""), headers))
for group, members in relationship_groups.items():
    institutions = {institution for institution, _ in members if institution}
    common_headers = set(members[0][1]).intersection(*(set(headers) for _, headers in members[1:])) if members else set()
    require(len(institutions) >= 2, f"business_data_relationship:{group}:institutions")
    require(bool(common_headers), f"business_data_relationship:{group}:common_fields")

result = {"status": "passed" if not ERRORS else "failed", "checks": len(CHECKS), "errors": ERRORS}
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
raise SystemExit(0 if not ERRORS else 1)
