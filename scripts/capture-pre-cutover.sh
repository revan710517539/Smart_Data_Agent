#!/usr/bin/env sh
set -eu

sha=${1:-}
case "$sha" in *[!0-9a-f]*|'') echo "usage: $0 <40-character-git-sha>" >&2; exit 2 ;; esac
test "${#sha}" -eq 40 || { echo "usage: $0 <40-character-git-sha>" >&2; exit 2; }
command -v docker >/dev/null 2>&1 || { echo "Docker is required" >&2; exit 2; }
test "$(git rev-parse HEAD)" = "$sha" || { echo "requested SHA is not HEAD" >&2; exit 1; }
test -z "$(git status --porcelain --untracked-files=normal)" || { echo "worktree must be clean before pre-cutover capture" >&2; exit 1; }
test -s artifacts/release/candidate-identity.json || { echo "candidate identity receipt is required before pre-cutover capture" >&2; exit 2; }
test -n "${SMART_DATA_AGENT_PRODUCTION_URL:-}" || { echo "SMART_DATA_AGENT_PRODUCTION_URL is required" >&2; exit 2; }
test -n "${SMART_DATA_AGENT_CURRENT_PRODUCTION_CONTAINER:-}" || { echo "SMART_DATA_AGENT_CURRENT_PRODUCTION_CONTAINER is required" >&2; exit 2; }
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
root=$(pwd -P)
exec docker run --rm --platform "$target_platform" --network host \
  --volume "$root:/workspace" \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  --workdir /workspace \
  --env "SMART_DATA_AGENT_RELEASE_TOOLCHAIN_IMAGE_ID=$toolchain_image_id" \
  --env "SMART_DATA_AGENT_TARGET_PLATFORM=$target_platform" \
  "$toolchain_image_id" sh -eu -c '
    python scripts/release_gate_evidence.py verify \
      --commit-sha "$1" \
      --scope candidate \
      --toolchain-image-id "$SMART_DATA_AGENT_RELEASE_TOOLCHAIN_IMAGE_ID" \
      --target-platform "$SMART_DATA_AGENT_TARGET_PLATFORM"
    exec python scripts/pre_cutover_snapshot.py capture "$2" "$3" "$1"
  ' sh "$sha" "$SMART_DATA_AGENT_PRODUCTION_URL" "$SMART_DATA_AGENT_CURRENT_PRODUCTION_CONTAINER"
