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
uv run --frozen python - "$live" "$ready" "$expected_sha" <<'PY'
import json, sys
live, ready = map(json.loads, sys.argv[1:3])
expected_sha = sys.argv[3]
assert live.get("status") == "ok", live
assert ready.get("ready") is True, ready
assert (ready.get("build") or {}).get("commit_sha") == expected_sha, ready
required = {
    "database", "automation_worker", "rate_limiter", "object_store", "semantic_runtime",
    "capability_public_origin", "capability_wss", "capability_asr",
    "capability_data_crawler", "capability_authentication",
}
assert required <= set(ready.get("checks") or {}), ready
assert all((ready["checks"][name] or {}).get("ready") for name in required), ready
database = ready["checks"]["database"]
assert database.get("version") == "8.0.18", database
assert database.get("target_version") == "8.0.18", database
build = ready.get("build") or {}
assert all(len(str(build.get(key) or "")) == 64 for key in (
    "source_archive_sha256", "dependency_lock_sha256", "frontend_assets_sha256", "release_toolchain_sha256"
)), build
assert __import__("re").fullmatch(r".+@sha256:[0-9a-f]{64}", str(build.get("image_reference") or "")), build
runtime = ready.get("runtime") or {}
assert 0 < len(str(runtime.get("instance_id") or "")) <= 128, runtime
PY
headers=$(mktemp)
html=$(mktemp)
assets=$(mktemp)
timings=$(mktemp)
trap 'rm -f "$headers" "$html" "$assets" "$timings"' EXIT HUP INT TERM
curl --fail --silent --show-error --max-time 15 -D "$headers" -o "$html" -w 'root=%{time_total}\n' "$base_url/" > "$timings"
grep -qi '^content-type: text/html' "$headers"
uv run --frozen python - "$html" > "$assets" <<'PY'
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
uv run --frozen python - "$timings" "$expected_sha" <<'PY'
import json, sys
print(json.dumps({
    "status": "passed",
    "commit_sha": sys.argv[2],
    "timings": open(sys.argv[1], encoding="utf-8").read().splitlines(),
}, sort_keys=True))
PY
