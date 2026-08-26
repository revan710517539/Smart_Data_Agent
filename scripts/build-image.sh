#!/usr/bin/env sh
set -eu

sha=${1:-}
case "$sha" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) echo "usage: $0 <40-character-git-sha>" >&2; exit 2 ;;
esac

test "$(git rev-parse HEAD)" = "$sha" || { echo "requested SHA is not HEAD" >&2; exit 1; }
test -z "$(git status --porcelain --untracked-files=normal)" || { echo "worktree must be clean for an immutable image" >&2; exit 1; }
test -s artifacts/release/python-environment.json || { echo "frozen Python environment marker missing" >&2; exit 1; }
test -s artifacts/release/release-identity.json || { echo "release identity missing" >&2; exit 1; }
test -s artifacts/release/release-gate-report.json || { echo "release gate report missing" >&2; exit 1; }
uv run --frozen python scripts/check_production_development_standard.py
target_platform=${SMART_DATA_AGENT_TARGET_PLATFORM:-}
case "$target_platform" in
  linux/amd64|linux/arm64) ;;
  *) echo "SMART_DATA_AGENT_TARGET_PLATFORM must be exactly linux/amd64 or linux/arm64" >&2; exit 2 ;;
esac
image=${SMART_DATA_AGENT_IMAGE_REPOSITORY:-smart-data-agent}:$sha
build_date=$(git show -s --format=%cI "$sha")
source_archive_sha256=$(uv run --frozen python scripts/release_identity.py get source_archive_sha256)
dependency_lock_sha256=$(uv run --frozen python scripts/release_identity.py get dependency_lock_sha256)
frontend_assets_sha256=$(uv run --frozen python scripts/release_identity.py get frontend_assets_sha256)
release_toolchain_sha256=$(uv run --frozen python scripts/release_identity.py get release_toolchain_sha256)
offline=${SMART_DATA_AGENT_RELEASE_OFFLINE:-false}
case "$offline" in true|false) ;; *) echo "SMART_DATA_AGENT_RELEASE_OFFLINE must be exactly true or false" >&2; exit 2 ;; esac
temporary_cache_context=$(mktemp -d)
cleanup_cache_context() {
  rm -rf "$temporary_cache_context"
}
trap cleanup_cache_context EXIT HUP INT TERM
if test "$offline" = true; then
  test -d /release-cache/npm && test -d /release-cache/wheelhouse || { echo "validated offline release cache is unavailable" >&2; exit 2; }
  cache_context=/release-cache
else
  mkdir -p "$temporary_cache_context/npm" "$temporary_cache_context/wheelhouse"
  cache_context=$temporary_cache_context
fi
set -- docker build --platform "$target_platform" --build-context "release-cache=$cache_context" \
  --build-arg "SMART_DATA_AGENT_RELEASE_OFFLINE=$offline" \
  --build-arg "SMART_DATA_AGENT_COMMIT_SHA=$sha" \
  --build-arg "SMART_DATA_AGENT_BUILD_DATE=$build_date" \
  --build-arg "SMART_DATA_AGENT_SOURCE_ARCHIVE_SHA256=$source_archive_sha256" \
  --build-arg "SMART_DATA_AGENT_DEPENDENCY_LOCK_SHA256=$dependency_lock_sha256" \
  --build-arg "SMART_DATA_AGENT_FRONTEND_ASSETS_SHA256=$frontend_assets_sha256" \
  --build-arg "SMART_DATA_AGENT_RELEASE_TOOLCHAIN_SHA256=$release_toolchain_sha256" \
  --label "org.opencontainers.image.revision=$sha" \
  --tag "$image"
if test "$offline" = true; then
  set -- "$@" --network none
fi
DOCKER_BUILDKIT=1 "$@" .
trap - EXIT HUP INT TERM
cleanup_cache_context
image_revision=$(docker image inspect "$image" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')
test "$image_revision" = "$sha" || { echo "image revision label mismatch" >&2; exit 1; }
image_platform=$(docker image inspect "$image" --format '{{.Os}}/{{.Architecture}}')
test "$image_platform" = "$target_platform" || { echo "application image platform mismatch: expected $target_platform, got $image_platform" >&2; exit 1; }
uv run --frozen python scripts/collect_release_evidence.py "$image" "$sha"
printf '%s\n' "$image"
