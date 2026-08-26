#!/usr/bin/env sh
set -eu

sha=${1:-}
scope=${SMART_DATA_AGENT_RELEASE_SCOPE:-candidate}
case "$scope" in build|candidate) ;; *) echo "SMART_DATA_AGENT_RELEASE_SCOPE must be build or candidate" >&2; exit 2 ;; esac
case "${SMART_DATA_AGENT_TARGET_PLATFORM:-}" in
  linux/amd64|linux/arm64) ;;
  *) echo "SMART_DATA_AGENT_TARGET_PLATFORM must be exactly linux/amd64 or linux/arm64" >&2; exit 2 ;;
esac
git config --global --add safe.directory /workspace
test "$(git rev-parse HEAD)" = "$sha" || { echo "release SHA changed after toolchain start" >&2; exit 1; }
test -z "$(git status --porcelain --untracked-files=normal)" || { echo "worktree changed after toolchain start" >&2; exit 1; }
unset VIRTUAL_ENV

python scripts/release_gate_evidence.py start --commit-sha "$sha" --scope "$scope"
gate_finished=false
finish_on_exit() {
  exit_code=$?
  trap - EXIT
  if test "$gate_finished" != true; then
    python scripts/release_gate_evidence.py finish --status failed >/dev/null 2>&1 || true
  fi
  exit "$exit_code"
}
trap finish_on_exit EXIT

run_step() {
  name=$1
  shift
  started_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
  set +e
  "$@"
  exit_code=$?
  set -e
  completed_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
  if test "$exit_code" -eq 0; then
    step_status=passed
  else
    step_status=failed
  fi
  python scripts/release_gate_evidence.py step \
    --name "$name" \
    --started-at "$started_at" \
    --completed-at "$completed_at" \
    --status "$step_status" \
    --exit-code "$exit_code" \
    -- "$@"
  return "$exit_code"
}

require_nonempty_env() {
  name=$1
  value=$(printenv "$name" 2>/dev/null || true)
  test -n "$value" || { echo "$name is required by the release gate" >&2; return 1; }
}

run_step toolchain_contract python scripts/check_release_toolchain.py
if test -n "${SMART_DATA_AGENT_RELEASE_CACHE_MANIFEST_SHA256:-}"; then
  run_step release_cache python scripts/release_cache_manifest.py verify /release-cache "$SMART_DATA_AGENT_RELEASE_CACHE_MANIFEST_SHA256"
fi
run_step mysql_8_0_18_configuration require_nonempty_env SMART_DATA_AGENT_TEST_MYSQL_URL
run_step python_environment sh scripts/sync-python-environment.sh
if test "${SMART_DATA_AGENT_RELEASE_OFFLINE:-false}" = true; then
  run_step node_dependencies npm ci --ignore-scripts --offline
else
  run_step node_dependencies npm ci --ignore-scripts
fi
export CHROME_PATH
CHROME_PATH=$(node -e 'process.stdout.write(require("playwright").chromium.executablePath())')
run_step browser_contract node scripts/browser-executable-contract.mjs

run_step personal_path_gate uv run --frozen python scripts/check_no_personal_paths.py
run_step development_standard uv run --frozen python scripts/check_production_development_standard.py
run_step migration_history uv run --frozen python scripts/check_mysql_migration_history.py
run_step deployment_contract uv run --frozen python scripts/check_server_deployment_contract.py
run_step mysql_sql_closure uv run --frozen python scripts/check_mysql_sql_closure.py
run_step production_capability_pack uv run --frozen python scripts/check_production_capability_pack.py
run_step database_schema uv run --frozen python scripts/generate_database_schema.py --check
run_step api_client uv run --frozen python scripts/generate_api_client.py --check
run_step frontend_module_size uv run --frozen python scripts/check_frontend_module_size.py
run_step python_dependency_audit uv run --frozen python -m pip_audit -r requirements.lock
run_step python_runtime_dependency_audit uv run --frozen python -m pip_audit -r requirements.runtime.lock
run_step node_dependency_audit npm audit --audit-level=moderate
run_step full_test_suite npm test

run_step mysql_8_0_18_integration uv run --frozen python -m unittest \
  backend.platform.tests.test_mysql_stores_integration \
  backend.platform.tests.test_mysql_sql_closure -v

run_step release_identity uv run --frozen python scripts/release_identity.py compute --commit-sha "$sha" --dist dist
run_step immutable_image sh scripts/build-image.sh "$sha"

if test "$scope" = candidate; then
  candidate_url=${SMART_DATA_AGENT_CANDIDATE_URL:-}
  test -n "$candidate_url" || { echo "SMART_DATA_AGENT_CANDIDATE_URL is required for a candidate release" >&2; exit 2; }
  export SMART_DATA_AGENT_EXPECTED_SHA=$sha
  run_step candidate_data_crawler_manifest sh scripts/data-crawler-contract-smoke.sh
  run_step candidate_business_smoke sh scripts/candidate-smoke.sh "$candidate_url"
  run_step candidate_authentication env \
    SMART_DATA_AGENT_AUTH_E2E_MODE=candidate \
    SMART_DATA_AGENT_AUTH_E2E_URL="$candidate_url" \
    sh scripts/auth-e2e.sh
  run_step candidate_identity uv run --frozen python scripts/deployment_identity.py candidate "$candidate_url" "$sha" \
    --container "$SMART_DATA_AGENT_CANDIDATE_CONTAINER" \
    --data-crawler-mount-type "$DATA_CRAWLER_MOUNT_TYPE" \
    --data-crawler-mount-source "$DATA_CRAWLER_MOUNT_SOURCE" \
    --target-platform "$SMART_DATA_AGENT_TARGET_PLATFORM"
fi

image=${SMART_DATA_AGENT_IMAGE_REPOSITORY:-smart-data-agent}:$sha
# Record one evidence-pack command while the gate is still in progress, then
# finalize and refresh it so SHA256SUMS binds the completed gate report.
run_step release_evidence uv run --frozen python scripts/collect_release_evidence.py "$image" "$sha"
python scripts/release_gate_evidence.py finish --status passed
uv run --frozen python scripts/collect_release_evidence.py "$image" "$sha"
gate_finished=true
trap - EXIT
printf '%s\n' "release gate passed scope=$scope sha=$sha image=$image"
