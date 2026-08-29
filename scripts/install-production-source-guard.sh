#!/bin/sh
set -eu
repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"
test -f .githooks/pre-push
test -f .release-guard/production-source.json
test -f scripts/production_source_guard.py
chmod +x .githooks/pre-push scripts/production_source_guard.py scripts/install-production-source-guard.sh
git config core.hooksPath .githooks
printf 'PRODUCTION_SOURCE_GUARD_INSTALLED\n'
printf 'core.hooksPath=%s\n' "$(git config --get core.hooksPath)"
