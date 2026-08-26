#!/usr/bin/env sh
set -eu

. scripts/data-crawler-mount-contract.sh

sha=${1:-}
case "$sha" in
  *[!0-9a-f]*|'') echo "usage: $0 <40-character-git-sha>" >&2; exit 2 ;;
esac
test "${#sha}" -eq 40 || { echo "usage: $0 <40-character-git-sha>" >&2; exit 2; }
command -v docker >/dev/null 2>&1 || { echo "Docker is required; host Node, npm, Python and browsers are intentionally ignored" >&2; exit 2; }
test "$(git rev-parse HEAD)" = "$sha" || { echo "requested SHA is not HEAD" >&2; exit 1; }
test -z "$(git status --porcelain --untracked-files=normal)" || { echo "worktree must be clean before production verification" >&2; exit 1; }
test -n "${SMART_DATA_AGENT_PRODUCTION_URL:-}" || { echo "SMART_DATA_AGENT_PRODUCTION_URL is required" >&2; exit 2; }
test -n "${SMART_DATA_AGENT_PRODUCTION_CONTAINER:-}" || { echo "SMART_DATA_AGENT_PRODUCTION_CONTAINER is required" >&2; exit 2; }
resolve_data_crawler_mount_contract true
data_crawler_mount_spec=$(data_crawler_docker_mount_spec ro)
for name in \
  SMART_DATA_AGENT_ANALYSIS_E2E_TENANT_ID \
  SMART_DATA_AGENT_ANALYSIS_E2E_RELATIVE_PATH \
  SMART_DATA_AGENT_ANALYSIS_E2E_CONTENT_HASH \
  SMART_DATA_AGENT_ANALYSIS_E2E_QUESTION
do
  value=$(printenv "$name" 2>/dev/null || true)
  test -n "$value" || { echo "$name is required for production real-data analysis" >&2; exit 2; }
done
case "$SMART_DATA_AGENT_ANALYSIS_E2E_RELATIVE_PATH" in
  /*|..|../*|*/../*|*/..) echo "SMART_DATA_AGENT_ANALYSIS_E2E_RELATIVE_PATH must be a safe relative path" >&2; exit 2 ;;
esac
case "$SMART_DATA_AGENT_ANALYSIS_E2E_CONTENT_HASH" in
  *[!0-9a-f]*|'') echo "SMART_DATA_AGENT_ANALYSIS_E2E_CONTENT_HASH must be a full lowercase SHA-256" >&2; exit 2 ;;
esac
test "${#SMART_DATA_AGENT_ANALYSIS_E2E_CONTENT_HASH}" -eq 64 || { echo "SMART_DATA_AGENT_ANALYSIS_E2E_CONTENT_HASH must contain 64 characters" >&2; exit 2; }
test -s artifacts/release/candidate-identity.json || { echo "candidate identity receipt is required before production verification" >&2; exit 2; }
test -s artifacts/release/pre-cutover-snapshot.json || { echo "pre-cutover rollback snapshot is required before production verification" >&2; exit 2; }

target_platform=${SMART_DATA_AGENT_TARGET_PLATFORM:-}
case "$target_platform" in
  linux/amd64|linux/arm64) ;;
  *) echo "SMART_DATA_AGENT_TARGET_PLATFORM must be exactly linux/amd64 or linux/arm64" >&2; exit 2 ;;
esac

toolchain_image_id=${SMART_DATA_AGENT_RELEASE_TOOLCHAIN_IMAGE_ID:-}
case "$toolchain_image_id" in sha256:*) ;; *) echo "SMART_DATA_AGENT_RELEASE_TOOLCHAIN_IMAGE_ID is required" >&2; exit 2 ;; esac
toolchain_id_digest=${toolchain_image_id#sha256:}
case "$toolchain_id_digest" in *[!0-9a-f]*|'') echo "SMART_DATA_AGENT_RELEASE_TOOLCHAIN_IMAGE_ID is invalid" >&2; exit 2 ;; esac
test "${#toolchain_id_digest}" -eq 64 || { echo "SMART_DATA_AGENT_RELEASE_TOOLCHAIN_IMAGE_ID is invalid" >&2; exit 2; }
docker image inspect "$toolchain_image_id" >/dev/null
toolchain_platform=$(docker image inspect "$toolchain_image_id" --format '{{.Os}}/{{.Architecture}}')
test "$toolchain_platform" = "$target_platform" || {
  echo "release toolchain platform mismatch: expected $target_platform, got $toolchain_platform" >&2
  exit 1
}

profile=${SMART_DATA_AGENT_PRODUCTION_AUTH_E2E_CHROME_PROFILE:-}
test -n "$profile" || { echo "SMART_DATA_AGENT_PRODUCTION_AUTH_E2E_CHROME_PROFILE is required" >&2; exit 2; }
test -d "$profile" || { echo "production browser profile directory is unavailable" >&2; exit 2; }
root=$(pwd -P)
exec docker run --rm --platform "$target_platform" --network host \
  --volume "$root:/workspace" \
  --volume /workspace/node_modules \
  --volume /workspace/.venv \
  --volume smart-data-agent-release-uv-cache:/root/.cache/uv \
  --volume smart-data-agent-release-npm-cache:/root/.npm \
  --volume "$profile:/release-browser-profile" \
  --mount "$data_crawler_mount_spec" \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  --workdir /workspace \
  --env "SMART_DATA_AGENT_PRODUCTION_URL=$SMART_DATA_AGENT_PRODUCTION_URL" \
  --env "SMART_DATA_AGENT_PRODUCTION_CONTAINER=$SMART_DATA_AGENT_PRODUCTION_CONTAINER" \
  --env "DATA_CRAWLER_MOUNT_TYPE=$DATA_CRAWLER_MOUNT_TYPE" \
  --env "DATA_CRAWLER_MOUNT_SOURCE=$DATA_CRAWLER_MOUNT_SOURCE" \
  --env "SMART_DATA_AGENT_RELEASE_TOOLCHAIN_IMAGE_ID=$toolchain_image_id" \
  --env "SMART_DATA_AGENT_TARGET_PLATFORM=$target_platform" \
  --env SMART_DATA_AGENT_ANALYSIS_E2E_TENANT_ID \
  --env SMART_DATA_AGENT_ANALYSIS_E2E_RELATIVE_PATH \
  --env SMART_DATA_AGENT_ANALYSIS_E2E_CONTENT_HASH \
  --env SMART_DATA_AGENT_ANALYSIS_E2E_QUESTION \
  --env SMART_DATA_AGENT_ANALYSIS_E2E_TIMEOUT_MS \
  --env SMART_DATA_AGENT_AUTH_E2E_CHROME_PROFILE=/release-browser-profile \
  --env SMART_DATA_AGENT_IMAGE_REPOSITORY \
  "$toolchain_image_id" sh scripts/verify-production-release-in-toolchain.sh "$sha"
