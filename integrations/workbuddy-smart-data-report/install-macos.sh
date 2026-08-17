#!/bin/sh
set -eu

BUNDLE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
ENDPOINT=""
APP_URL=""
WORKBUDDY_CLI=${WORKBUDDY_CLI:-/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy}
ALLOW_LOCAL_DEV=0
SKIP_SERVER_CHECK=0
SKIP_TOKEN_CHECK=0

usage() {
  echo "Usage: install-macos.sh --server-url <https://sda.example> [--app-url <https://sda.example>]" >&2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --bundle-root|--project-root) BUNDLE_ROOT=${2:-}; shift 2 ;;
    --server-url|--endpoint) ENDPOINT=${2:-}; shift 2 ;;
    --app-url) APP_URL=${2:-}; shift 2 ;;
    --workbuddy-cli) WORKBUDDY_CLI=${2:-}; shift 2 ;;
    --allow-local-dev) ALLOW_LOCAL_DEV=1; shift ;;
    --skip-server-check) SKIP_SERVER_CHECK=1; shift ;;
    --skip-token-check) SKIP_TOKEN_CHECK=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

validate_url() {
  label=$1
  value=$2
  case "$value" in
    https://*) ;;
    http://127.0.0.1:*|http://localhost:*)
      [ "$ALLOW_LOCAL_DEV" -eq 1 ] || { echo "$label must use HTTPS; localhost requires --allow-local-dev" >&2; exit 2; }
      ;;
    *) echo "$label must be an explicit HTTPS URL without an API path" >&2; exit 2 ;;
  esac
  case "$value" in
    *\"*|*\\*|*' '*|*\?*|*\#*|*@*|*/api/*) echo "$label is malformed or contains credentials, query, fragment or an API path" >&2; exit 2 ;;
  esac
}

[ -n "$ENDPOINT" ] || { echo "--server-url is required; use the exact HTTPS SDA address supplied by your administrator" >&2; usage; exit 2; }
ENDPOINT=${ENDPOINT%/}
validate_url "--server-url" "$ENDPOINT"
if [ -z "$APP_URL" ]; then APP_URL="$ENDPOINT"; else APP_URL=${APP_URL%/}; validate_url "--app-url" "$APP_URL"; fi

command -v python3 >/dev/null 2>&1 || { echo "Python 3.10+ is required before installing SDA Bridge." >&2; exit 2; }
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 2)' || { echo "Python 3.10+ is required before installing SDA Bridge." >&2; exit 2; }

if [ "$SKIP_SERVER_CHECK" -eq 1 ] && [ "$ALLOW_LOCAL_DEV" -ne 1 ]; then
  echo "--skip-server-check is restricted to explicit local development" >&2
  exit 2
fi
if [ "$SKIP_SERVER_CHECK" -eq 0 ]; then
  MANIFEST_FILE=$(mktemp -t sda-bridge-manifest.XXXXXX)
  trap 'rm -f "$MANIFEST_FILE"' EXIT HUP INT TERM
  curl --fail --silent --show-error --proto '=https' --tlsv1.2 \
    "$ENDPOINT/api/integrations/bridge/distribution/manifest" -o "$MANIFEST_FILE"
  python3 - "$MANIFEST_FILE" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
if manifest.get("schema_version") != "sda_bridge_distribution_v1" or "workbuddy" not in (manifest.get("channels") or []):
    raise SystemExit("SDA server does not expose the expected WorkBuddy Bridge contract")
PY
  rm -f "$MANIFEST_FILE"
  trap - EXIT HUP INT TERM
fi

PLUGIN_ROOT="$BUNDLE_ROOT/integrations/workbuddy-smart-data-report"
MARKETPLACE_DIR="$BUNDLE_ROOT/integrations/workbuddy-smart-data-report-marketplace"
CONFIG_DIR="$HOME/.config/smart-data-agent"
TOKEN_SERVICE="smart-data-agent-report-token"
MARKETPLACE_NAME="smart-data-agent-official"

test -x "$WORKBUDDY_CLI" || { echo "WorkBuddy CLI not found: $WORKBUDDY_CLI" >&2; exit 2; }
test -f "$PLUGIN_ROOT/.codebuddy-plugin/plugin.json" || { echo "Bridge package is incomplete: WorkBuddy plugin missing" >&2; exit 2; }
test -f "$MARKETPLACE_DIR/.codebuddy-plugin/marketplace.json" || { echo "Bridge package is incomplete: WorkBuddy marketplace missing" >&2; exit 2; }
"$WORKBUDDY_CLI" plugin validate "$PLUGIN_ROOT"
"$WORKBUDDY_CLI" plugin validate "$MARKETPLACE_DIR"
if ! "$WORKBUDDY_CLI" plugin marketplace list | grep -q "$MARKETPLACE_NAME"; then
  "$WORKBUDDY_CLI" plugin marketplace add "$MARKETPLACE_DIR" --name "$MARKETPLACE_NAME"
fi
if ! "$WORKBUDDY_CLI" plugin install "smart-data-agent-report@$MARKETPLACE_NAME" --scope user; then
  "$WORKBUDDY_CLI" plugin enable "smart-data-agent-report@$MARKETPLACE_NAME" --scope user
fi

umask 077
mkdir -p "$CONFIG_DIR"
python3 - "$CONFIG_DIR/report-cli.json" "$ENDPOINT" "$APP_URL" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
path.write_text(json.dumps({"endpoint": sys.argv[2], "app_url": sys.argv[3]}, ensure_ascii=False) + "\n", encoding="utf-8")
PY
if [ "$SKIP_TOKEN_CHECK" -eq 0 ]; then
  if ! security find-generic-password -a "$USER" -s "$TOKEN_SERVICE" >/dev/null 2>&1; then
    "$PLUGIN_ROOT/bin/SDA" connect --channel workbuddy \
      --endpoint "$ENDPOINT" --app-url "$APP_URL" --token-keychain-service "$TOKEN_SERVICE"
  fi
  "$PLUGIN_ROOT/bin/SDA" bridge --channel workbuddy systems \
    --token-keychain-service "$TOKEN_SERVICE" --json >/dev/null
  "$PLUGIN_ROOT/bin/SDA" bridge --channel workbuddy context --system sda \
    --token-keychain-service "$TOKEN_SERVICE" --json >/dev/null
fi
echo "Universal WorkBuddy Bridge ready: server=$ENDPOINT"
echo "Restart WorkBuddy before the first analysis."
