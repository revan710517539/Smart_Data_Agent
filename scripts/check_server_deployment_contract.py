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
dev_compose = read("docker-compose.dev.yml")
server_compose = read("docker-compose.server.yml")
production_lock = read("requirements.lock")
runtime_lock = read("requirements.runtime.lock")
ci = read(".github/workflows/ci.yml")
release_gate = read("scripts/release-gate.sh")
readme = read("README.md")
deployment_doc = read("docs/server_mysql_deployment.md")
business_data_manifest_text = read("src/app/data/business-data-manifest.json")

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
    require("/app/data:ro" in content, f"{label}_read_only_data_mount")
    require("SMART_DATA_AGENT_DATA_WAREHOUSE: csv" in content, f"{label}_csv_warehouse")
    require("SMART_DATA_AGENT_DATABASE_URL" in content, f"{label}_mysql_secret_reference")
    require(
        "/app/Origin_Data" not in content and "SMART_DATA_AGENT_CSV_SOURCE_ROOT" not in content,
        f"{label}_no_retired_source",
    )
require("/opt/palywright/examples/data-crawler/data" in server_compose, "server_compose_host_data_contract")
require("runtime-data" not in server_compose, "server_compose_no_legacy_runtime_data")
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
require("SMART_DATA_AGENT_IMAGE:?set an immutable 40-character SHA image tag" in server_compose, "server_compose_immutable_image")
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

require("image: mysql:8.0.18" in ci, "ci_mysql_8018")
require("SMART_DATA_AGENT_TEST_MYSQL_URL" in ci, "ci_mysql_integration_url")
require(
    "SMART_DATA_AGENT_TEST_POSTGRES_URL" not in ci and "image: postgres:" not in ci,
    "ci_no_postgresql_primary",
)
require("scripts/release-gate.sh" in ci, "ci_release_gate")
require("check_server_deployment_contract.py" in release_gate, "release_gate_deployment_contract")
require("check_production_capability_pack.py" in release_gate, "release_gate_capability_pack")
require("scripts/build-image.sh" in ci, "ci_immutable_image_builder")

for content, label in ((readme, "readme"), (deployment_doc, "deployment_doc")):
    require(
        "SMART_DATA_AGENT_DATA_CRAWLER_ROOT" in content and "/app/data" in content,
        f"{label}_current_source_contract",
    )
    require("scripts/provision_production.py" in content, f"{label}_explicit_empty_database_provision")
    require("/opt/palywright/examples/data-crawler/data" in content, f"{label}_server_host_path")

for script in (
    "scripts/release-gate.sh",
    "scripts/check-mysql-closure.sh",
    "scripts/build-image.sh",
    "scripts/candidate-smoke.sh",
    "scripts/auth-e2e.sh",
    "scripts/data-crawler-contract-smoke.sh",
    "scripts/collect_release_evidence.py",
):
    require((ROOT / script).is_file(), f"release_script:{script}")

require("org.opencontainers.image.revision" in dockerfile, "dockerfile_commit_label")
require("SMART_DATA_AGENT_COMMIT_SHA=${SMART_DATA_AGENT_COMMIT_SHA}" in dockerfile, "dockerfile_runtime_commit_sha")
require("collect_release_evidence.py" in read("scripts/build-image.sh"), "build_image_release_evidence")
require("SMART_DATA_AGENT_EXPECTED_SHA" in read("scripts/candidate-smoke.sh"), "candidate_exact_sha")
require("check_frontend_delivery.mjs" in dockerfile, "dockerfile_frontend_delivery_gate")

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
