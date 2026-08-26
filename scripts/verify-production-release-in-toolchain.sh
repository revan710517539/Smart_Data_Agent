#!/usr/bin/env sh
set -eu

sha=${1:-}
production_url=${SMART_DATA_AGENT_PRODUCTION_URL:-}
git config --global --add safe.directory /workspace
test "$(git rev-parse HEAD)" = "$sha" || { echo "production verification SHA changed" >&2; exit 1; }
unset VIRTUAL_ENV
sh scripts/sync-python-environment.sh
npm ci --ignore-scripts
export CHROME_PATH
CHROME_PATH=$(node -e 'process.stdout.write(require("playwright").chromium.executablePath())')
node scripts/browser-executable-contract.mjs
python scripts/release_gate_evidence.py verify \
  --commit-sha "$sha" \
  --scope candidate \
  --toolchain-image-id "$SMART_DATA_AGENT_RELEASE_TOOLCHAIN_IMAGE_ID" \
  --target-platform "$SMART_DATA_AGENT_TARGET_PLATFORM"
uv run --frozen python - "$sha" <<'PY'
import json, pathlib, sys
root = pathlib.Path("artifacts/release")
gate = json.loads((root / "release-gate-report.json").read_text(encoding="utf-8"))
candidate = json.loads((root / "candidate-identity.json").read_text(encoding="utf-8"))
pre_cutover = json.loads((root / "pre-cutover-snapshot.json").read_text(encoding="utf-8"))
sha = sys.argv[1]
assert (candidate.get("identity") or {}).get("commit_sha") == sha, candidate
assert (pre_cutover.get("target_release") or {}).get("commit_sha") == sha, pre_cutover
PY
python scripts/pre_cutover_snapshot.py verify artifacts/release/pre-cutover-snapshot.json "$sha"
export SMART_DATA_AGENT_EXPECTED_SHA=$sha
production_data_crawler_manifest() {
  sh scripts/data-crawler-contract-smoke.sh
}
production_data_crawler_manifest
sh scripts/candidate-smoke.sh "$production_url"
SMART_DATA_AGENT_AUTH_E2E_MODE=production SMART_DATA_AGENT_AUTH_E2E_URL="$production_url" sh scripts/auth-e2e.sh
uv run --frozen python scripts/deployment_identity.py production "$production_url" "$sha" \
  --compare artifacts/release/candidate-identity.json \
  --container "$SMART_DATA_AGENT_PRODUCTION_CONTAINER" \
  --data-crawler-mount-type "$DATA_CRAWLER_MOUNT_TYPE" \
  --data-crawler-mount-source "$DATA_CRAWLER_MOUNT_SOURCE" \
  --target-platform "$SMART_DATA_AGENT_TARGET_PLATFORM"
image=${SMART_DATA_AGENT_IMAGE_REPOSITORY:-smart-data-agent}:$sha
uv run --frozen python scripts/collect_release_evidence.py "$image" "$sha"
printf '%s\n' "production release verified sha=$sha url=$production_url"
