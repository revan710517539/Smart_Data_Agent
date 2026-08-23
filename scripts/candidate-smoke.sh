#!/usr/bin/env sh
set -eu

base_url=${1:-${SMART_DATA_AGENT_CANDIDATE_URL:-}}
test -n "$base_url" || { echo "candidate URL required" >&2; exit 2; }
base_url=${base_url%/}
live=$(curl --fail --silent --show-error --max-time 10 "$base_url/api/live")
ready=$(curl --fail --silent --show-error --max-time 15 "$base_url/api/ready")
python3 - "$live" "$ready" <<'PY'
import json, sys
live, ready = map(json.loads, sys.argv[1:])
assert live.get("status") == "ok", live
assert ready.get("ready") is True, ready
required = {"database", "automation_worker", "rate_limiter", "object_store", "semantic_runtime"}
assert required <= set(ready.get("checks") or {}), ready
assert all((ready["checks"][name] or {}).get("ready") for name in required), ready
PY
headers=$(mktemp)
trap 'rm -f "$headers"' EXIT HUP INT TERM
curl --fail --silent --show-error --compressed --max-time 15 -D "$headers" -o /dev/null "$base_url/"
grep -qi '^content-type: text/html' "$headers"
printf '%s\n' "candidate smoke passed"
