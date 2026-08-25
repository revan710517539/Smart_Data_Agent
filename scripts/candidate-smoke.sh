#!/usr/bin/env sh
set -eu

base_url=${1:-${SMART_DATA_AGENT_CANDIDATE_URL:-}}
test -n "$base_url" || { echo "candidate URL required" >&2; exit 2; }
base_url=${base_url%/}
expected_sha=${SMART_DATA_AGENT_EXPECTED_SHA:-}
case "$expected_sha" in
  *[!0-9a-f]*|'') echo "SMART_DATA_AGENT_EXPECTED_SHA must be the deployed 40-character SHA" >&2; exit 2 ;;
esac
test "${#expected_sha}" -eq 40 || { echo "SMART_DATA_AGENT_EXPECTED_SHA must be the deployed 40-character SHA" >&2; exit 2; }
live=$(curl --fail --silent --show-error --max-time 10 "$base_url/api/live")
ready=$(curl --fail --silent --show-error --max-time 15 "$base_url/api/ready")
python3 - "$live" "$ready" "$expected_sha" <<'PY'
import json, sys
live, ready = map(json.loads, sys.argv[1:3])
expected_sha = sys.argv[3]
assert live.get("status") == "ok", live
assert ready.get("ready") is True, ready
assert (ready.get("build") or {}).get("commit_sha") == expected_sha, ready
required = {"database", "automation_worker", "rate_limiter", "object_store", "semantic_runtime"}
assert required <= set(ready.get("checks") or {}), ready
assert all((ready["checks"][name] or {}).get("ready") for name in required), ready
database = ready["checks"]["database"]
assert database.get("version") == "8.0.18", database
assert database.get("target_version") == "8.0.18", database
PY
headers=$(mktemp)
html=$(mktemp)
assets=$(mktemp)
timings=$(mktemp)
trap 'rm -f "$headers" "$html" "$assets" "$timings"' EXIT HUP INT TERM
curl --fail --silent --show-error --max-time 15 -D "$headers" -o "$html" -w 'root=%{time_total}\n' "$base_url/" > "$timings"
grep -qi '^content-type: text/html' "$headers"
python3 - "$html" > "$assets" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
for asset in sorted(set(re.findall(r'(?:src|href)=["\']([^"\']+\.(?:js|css))["\']', text))):
    print(asset)
PY
test -s "$assets" || { echo "candidate HTML has no JS/CSS assets" >&2; exit 1; }
while IFS= read -r asset; do
  case "$asset" in
    http://*|https://*) asset_url=$asset ;;
    /*) asset_url=$base_url$asset ;;
    *) asset_url=$base_url/$asset ;;
  esac
  curl --fail --silent --show-error --compressed --max-time 15 -o /dev/null \
    -w "asset=$asset time=%{time_total} status=%{http_code}\n" "$asset_url" >> "$timings"
done < "$assets"
python3 - "$timings" "$expected_sha" <<'PY'
import json, sys
print(json.dumps({
    "status": "passed",
    "commit_sha": sys.argv[2],
    "timings": open(sys.argv[1], encoding="utf-8").read().splitlines(),
}, sort_keys=True))
PY
