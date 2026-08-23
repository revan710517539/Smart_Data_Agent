#!/usr/bin/env sh
set -eu

sha=${1:-}
case "$sha" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) echo "usage: $0 <40-character-git-sha>" >&2; exit 2 ;;
esac

test "$(git rev-parse HEAD)" = "$sha" || { echo "requested SHA is not HEAD" >&2; exit 1; }
test -z "$(git status --porcelain --untracked-files=normal)" || { echo "worktree must be clean for an immutable image" >&2; exit 1; }
image=${SMART_DATA_AGENT_IMAGE_REPOSITORY:-smart-data-agent}:$sha
build_date=$(git show -s --format=%cI "$sha")
docker build \
  --build-arg "SMART_DATA_AGENT_COMMIT_SHA=$sha" \
  --build-arg "SMART_DATA_AGENT_BUILD_DATE=$build_date" \
  --label "org.opencontainers.image.revision=$sha" \
  --tag "$image" .
image_revision=$(docker image inspect "$image" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')
test "$image_revision" = "$sha" || { echo "image revision label mismatch" >&2; exit 1; }
printf '%s\n' "$image"
