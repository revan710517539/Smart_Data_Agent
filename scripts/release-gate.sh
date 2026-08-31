#!/usr/bin/env sh
set -eu

. scripts/data-crawler-mount-contract.sh

sha=${1:-}
case "$sha" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) echo "usage: $0 <40-character-git-sha>" >&2; exit 2 ;;
esac
command -v docker >/dev/null 2>&1 || { echo "Docker is required; host Node, npm, Python and browsers are intentionally ignored" >&2; exit 2; }
test "$(git rev-parse HEAD)" = "$sha" || { echo "requested SHA is not HEAD" >&2; exit 1; }
test -z "$(git status --porcelain --untracked-files=normal)" || { echo "worktree must be clean before the release gate" >&2; exit 1; }

scope=${SMART_DATA_AGENT_RELEASE_SCOPE:-candidate}
case "$scope" in build|candidate) ;; *) echo "SMART_DATA_AGENT_RELEASE_SCOPE must be build or candidate" >&2; exit 2 ;; esac
target_platform=${SMART_DATA_AGENT_TARGET_PLATFORM:-}
case "$target_platform" in
  linux/amd64|linux/arm64) ;;
  *) echo "SMART_DATA_AGENT_TARGET_PLATFORM must be exactly linux/amd64 or linux/arm64" >&2; exit 2 ;;
esac
offline=${SMART_DATA_AGENT_RELEASE_OFFLINE:-false}
case "$offline" in true|false) ;; *) echo "SMART_DATA_AGENT_RELEASE_OFFLINE must be exactly true or false" >&2; exit 2 ;; esac
cache_root=${SMART_DATA_AGENT_RELEASE_CACHE_ROOT:-}
cache_manifest_sha256=${SMART_DATA_AGENT_RELEASE_CACHE_MANIFEST_SHA256:-}
if test -n "$cache_root" || test -n "$cache_manifest_sha256" || test "$offline" = true; then
  test -n "$cache_root" || { echo "SMART_DATA_AGENT_RELEASE_CACHE_ROOT is required for a validated release cache" >&2; exit 2; }
  test -d "$cache_root" || { echo "SMART_DATA_AGENT_RELEASE_CACHE_ROOT is unavailable" >&2; exit 2; }
  case "$cache_manifest_sha256" in *[!0-9a-f]*|'') echo "SMART_DATA_AGENT_RELEASE_CACHE_MANIFEST_SHA256 must be 64 lowercase hexadecimal characters" >&2; exit 2 ;; esac
  test "${#cache_manifest_sha256}" -eq 64 || { echo "SMART_DATA_AGENT_RELEASE_CACHE_MANIFEST_SHA256 must contain 64 characters" >&2; exit 2; }
fi
root=$(pwd -P)
toolchain_image=${SMART_DATA_AGENT_TOOLCHAIN_IMAGE:-}
test "$scope" != candidate || test -n "$toolchain_image" || {
  echo "candidate release requires SMART_DATA_AGENT_TOOLCHAIN_IMAGE as an immutable repository@sha256 digest" >&2
  exit 2
}
if test -n "$toolchain_image"; then
  case "$toolchain_image" in
    *@sha256:*) ;;
    *) echo "SMART_DATA_AGENT_TOOLCHAIN_IMAGE must be an immutable repository@sha256 digest" >&2; exit 2 ;;
  esac
  toolchain_digest=${toolchain_image##*@sha256:}
  case "$toolchain_digest" in *[!0-9a-f]*|'') echo "SMART_DATA_AGENT_TOOLCHAIN_IMAGE digest must be 64 lowercase hexadecimal characters" >&2; exit 2 ;; esac
  test "${#toolchain_digest}" -eq 64 || { echo "SMART_DATA_AGENT_TOOLCHAIN_IMAGE digest must contain 64 characters" >&2; exit 2; }
  if ! docker image inspect "$toolchain_image" >/dev/null 2>&1; then
    test "$offline" = false || { echo "offline release requires the immutable toolchain image to exist locally" >&2; exit 2; }
    docker pull --platform "$target_platform" "$toolchain_image"
  fi
else
  test "$offline" = false || { echo "offline release requires SMART_DATA_AGENT_TOOLCHAIN_IMAGE with a local immutable digest" >&2; exit 2; }
  toolchain_tag="smart-data-agent-release-toolchain:$sha"
  docker build --platform "$target_platform" --file Dockerfile.release-toolchain --tag "$toolchain_tag" .
  toolchain_image=$toolchain_tag
fi
toolchain_platform=$(docker image inspect "$toolchain_image" --format '{{.Os}}/{{.Architecture}}')
test "$toolchain_platform" = "$target_platform" || {
  echo "release toolchain platform mismatch: expected $target_platform, got $toolchain_platform" >&2
  exit 1
}
toolchain_image_id=$(docker image inspect "$toolchain_image" --format '{{.Id}}')
toolchain_id_digest=${toolchain_image_id#sha256:}
case "$toolchain_image_id" in sha256:*) ;; *) echo "release toolchain image ID is invalid" >&2; exit 1 ;; esac
case "$toolchain_id_digest" in *[!0-9a-f]*|'') echo "release toolchain image ID is invalid" >&2; exit 1 ;; esac
test "${#toolchain_id_digest}" -eq 64 || { echo "release toolchain image ID is invalid" >&2; exit 1; }

set -- docker run --rm --platform "$target_platform" --network host \
  --volume "$root:/workspace" \
  --volume /workspace/node_modules \
  --volume /workspace/.venv \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  --volume smart-data-agent-release-uv-cache:/root/.cache/uv \
  --volume smart-data-agent-release-npm-cache:/root/.npm \
  --workdir /workspace \
  --env "SMART_DATA_AGENT_RELEASE_SCOPE=$scope" \
  --env "SMART_DATA_AGENT_TARGET_PLATFORM=$target_platform" \
  --env "SMART_DATA_AGENT_RELEASE_OFFLINE=$offline" \
  --env "SMART_DATA_AGENT_RELEASE_TOOLCHAIN_IMAGE_ID=$toolchain_image_id" \
  --env "SMART_DATA_AGENT_RELEASE_CACHE_MANIFEST_SHA256=$cache_manifest_sha256" \
  --env SMART_DATA_AGENT_TEST_MYSQL_URL \
  --env SMART_DATA_AGENT_MIGRATION_BASE_REF \
  --env SMART_DATA_AGENT_IMAGE_REPOSITORY \
  --env DATA_CRAWLER_SHARED_VOLUME \
  --env SMART_DATA_AGENT_CANDIDATE_URL \
  --env SMART_DATA_AGENT_CANDIDATE_CONTAINER \
  --env SMART_DATA_AGENT_AUTH_E2E_URL \
  --env SMART_DATA_AGENT_AUTH_E2E_MODE \
  --env SMART_DATA_AGENT_ANALYSIS_E2E_TENANT_ID \
  --env SMART_DATA_AGENT_ANALYSIS_E2E_RELATIVE_PATH \
  --env SMART_DATA_AGENT_ANALYSIS_E2E_CONTENT_HASH \
  --env SMART_DATA_AGENT_ANALYSIS_E2E_QUESTION \
  --env SMART_DATA_AGENT_ANALYSIS_E2E_TIMEOUT_MS \
  --env SMART_DATA_AGENT_EXPECTED_SHA

if test -n "$cache_root"; then
  set -- "$@" --volume "$cache_root:/release-cache:ro" --env UV_CACHE_DIR=/release-cache/uv --env npm_config_cache=/release-cache/npm --env npm_config_logs_dir=/tmp/npm-logs
fi

if test "$scope" = candidate; then
  test -n "${SMART_DATA_AGENT_CANDIDATE_URL:-}" || { echo "SMART_DATA_AGENT_CANDIDATE_URL is required for a candidate release" >&2; exit 2; }
  test -n "${SMART_DATA_AGENT_CANDIDATE_CONTAINER:-}" || { echo "SMART_DATA_AGENT_CANDIDATE_CONTAINER is required for a candidate release" >&2; exit 2; }
  resolve_data_crawler_mount_contract true
  data_crawler_mount_spec=$(data_crawler_docker_mount_spec ro)
  for name in \
    SMART_DATA_AGENT_ANALYSIS_E2E_TENANT_ID \
    SMART_DATA_AGENT_ANALYSIS_E2E_RELATIVE_PATH \
    SMART_DATA_AGENT_ANALYSIS_E2E_CONTENT_HASH \
    SMART_DATA_AGENT_ANALYSIS_E2E_QUESTION
  do
    value=$(printenv "$name" 2>/dev/null || true)
    test -n "$value" || { echo "$name is required for candidate real-data analysis" >&2; exit 2; }
  done
  case "$SMART_DATA_AGENT_ANALYSIS_E2E_RELATIVE_PATH" in
    /*|..|../*|*/../*|*/..) echo "SMART_DATA_AGENT_ANALYSIS_E2E_RELATIVE_PATH must be a safe relative path" >&2; exit 2 ;;
  esac
  case "$SMART_DATA_AGENT_ANALYSIS_E2E_CONTENT_HASH" in
    *[!0-9a-f]*|'') echo "SMART_DATA_AGENT_ANALYSIS_E2E_CONTENT_HASH must be a full lowercase SHA-256" >&2; exit 2 ;;
  esac
  test "${#SMART_DATA_AGENT_ANALYSIS_E2E_CONTENT_HASH}" -eq 64 || { echo "SMART_DATA_AGENT_ANALYSIS_E2E_CONTENT_HASH must contain 64 characters" >&2; exit 2; }
  profile=${SMART_DATA_AGENT_AUTH_E2E_CHROME_PROFILE:-}
  test -n "$profile" || { echo "SMART_DATA_AGENT_AUTH_E2E_CHROME_PROFILE is required for a candidate release" >&2; exit 2; }
  test -d "$profile" || { echo "candidate browser profile directory is unavailable" >&2; exit 2; }
  set -- "$@" \
    --volume "$profile:/release-browser-profile" \
    --mount "$data_crawler_mount_spec" \
    --env "DATA_CRAWLER_MOUNT_TYPE=$DATA_CRAWLER_MOUNT_TYPE" \
    --env "DATA_CRAWLER_MOUNT_SOURCE=$DATA_CRAWLER_MOUNT_SOURCE" \
    --env SMART_DATA_AGENT_AUTH_E2E_CHROME_PROFILE=/release-browser-profile
fi

exec "$@" "$toolchain_image_id" sh scripts/release-gate-in-toolchain.sh "$sha"
