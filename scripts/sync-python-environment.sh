#!/usr/bin/env sh
set -eu

marker=artifacts/release/python-environment.json
unset VIRTUAL_ENV
test ! -e "$marker" || rm -f "$marker"
cleanup_incomplete() {
  test ! -e "$marker" || rm -f "$marker"
}
trap cleanup_incomplete HUP INT TERM
offline=${SMART_DATA_AGENT_RELEASE_OFFLINE:-false}
case "$offline" in true|false) ;; *) echo "SMART_DATA_AGENT_RELEASE_OFFLINE must be exactly true or false" >&2; exit 2 ;; esac
set -- uv sync --frozen --extra dev
if test "$offline" = true; then
  set -- "$@" --offline
fi
"$@"
uv run --frozen python scripts/write_python_environment_marker.py "$marker"
trap - HUP INT TERM
test -s "$marker" || { echo "python environment completion marker missing" >&2; exit 1; }
