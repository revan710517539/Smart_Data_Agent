#!/bin/sh
set -eu

CHANNEL=""
ENDPOINT=""
APP_URL=""
BUNDLE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
ALLOW_LOCAL_DEV=0
SKIP_SERVER_CHECK=0
SKIP_TOKEN_CHECK=0

usage() {
  echo "Usage: install-macos.sh --channel <codex|qwork> --server-url <https://sda.example> [--app-url <https://sda.example>]" >&2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --channel) CHANNEL=${2:-}; shift 2 ;;
    --server-url|--endpoint) ENDPOINT=${2:-}; shift 2 ;;
    --app-url) APP_URL=${2:-}; shift 2 ;;
    --bundle-root|--project-root) BUNDLE_ROOT=${2:-}; shift 2 ;;
    --allow-local-dev) ALLOW_LOCAL_DEV=1; shift ;;
    --skip-server-check) SKIP_SERVER_CHECK=1; shift ;;
    --skip-token-check) SKIP_TOKEN_CHECK=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

case "$CHANNEL" in
  codex|qwork) ;;
  *) echo "--channel must be codex or qwork" >&2; usage; exit 2 ;;
esac

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
if [ -z "$APP_URL" ]; then
  APP_URL="$ENDPOINT"
else
  APP_URL=${APP_URL%/}
  validate_url "--app-url" "$APP_URL"
fi

command -v python3 >/dev/null 2>&1 || { echo "Python 3.10+ is required before installing SDA Bridge." >&2; exit 2; }
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 2)' || { echo "Python 3.10+ is required before installing SDA Bridge." >&2; exit 2; }

if [ "$SKIP_SERVER_CHECK" -eq 1 ] && [ "$ALLOW_LOCAL_DEV" -ne 1 ]; then
  echo "--skip-server-check is restricted to explicit local development" >&2
  exit 2
fi
if [ "$SKIP_SERVER_CHECK" -eq 0 ]; then
  command -v curl >/dev/null 2>&1 || { echo "curl is required to verify the SDA server." >&2; exit 2; }
  MANIFEST_FILE=$(mktemp -t sda-bridge-manifest.XXXXXX)
  trap 'rm -f "$MANIFEST_FILE"' EXIT HUP INT TERM
  curl --fail --silent --show-error --proto '=https' --tlsv1.2 \
    "$ENDPOINT/api/integrations/bridge/distribution/manifest" -o "$MANIFEST_FILE"
  python3 - "$MANIFEST_FILE" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
if manifest.get("schema_version") != "sda_bridge_distribution_v1":
    raise SystemExit("SDA server does not expose the expected Bridge distribution contract")
if set(manifest.get("channels") or []) != {"workbuddy", "codex", "qwork"}:
    raise SystemExit("SDA server Bridge channel contract is incomplete")
PY
  rm -f "$MANIFEST_FILE"
  trap - EXIT HUP INT TERM
fi

SOURCE_CLI="$BUNDLE_ROOT/integrations/workbuddy-smart-data-report/bin/sda_report.py"
SOURCE_SKILL="$BUNDLE_ROOT/integrations/${CHANNEL}-smart-data-agent-bridge/smart-data-agent-bridge/SKILL.md"
BRIDGE_ROOT="$HOME/.local/share/smart-data-agent-bridge/bin"
LAUNCHER_ROOT="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config/smart-data-agent"
TOKEN_SERVICE="smart-data-agent-bridge-$CHANNEL"

test -f "$SOURCE_CLI" || { echo "Bridge package is incomplete: $SOURCE_CLI" >&2; exit 2; }
test -f "$SOURCE_SKILL" || { echo "Bridge package is incomplete: $SOURCE_SKILL" >&2; exit 2; }

umask 077
mkdir -p "$BRIDGE_ROOT" "$LAUNCHER_ROOT" "$CONFIG_DIR"
install -m 600 "$SOURCE_CLI" "$BRIDGE_ROOT/sda_report.py"
install -m 700 "$BUNDLE_ROOT/integrations/smart-data-agent-bridge/SDA" "$LAUNCHER_ROOT/SDA"
python3 - "$CONFIG_DIR/report-cli.json" "$ENDPOINT" "$APP_URL" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
path.write_text(json.dumps({"endpoint": sys.argv[2], "app_url": sys.argv[3]}, ensure_ascii=False) + "\n", encoding="utf-8")
PY

install_skill() {
  target=$1
  mkdir -p "$target"
  install -m 600 "$SOURCE_SKILL" "$target/SKILL.md"
}

if [ "$CHANNEL" = "codex" ]; then
  CODEX_ROOT=${CODEX_HOME:-"$HOME/.codex"}
  install_skill "$CODEX_ROOT/skills/smart-data-agent-bridge"
else
  DEEPBANK_ROOT=${DEEPBANK_HOME:-"$HOME/.deepbank"}
  install_skill "$DEEPBANK_ROOT/.agents/skills/smart-data-agent-bridge"
  install_skill "$DEEPBANK_ROOT/.claude/skills/smart-data-agent-bridge"
fi

if [ "$SKIP_TOKEN_CHECK" -eq 0 ]; then
  if ! security find-generic-password -a "$USER" -s "$TOKEN_SERVICE" >/dev/null 2>&1; then
    "$LAUNCHER_ROOT/SDA" connect --channel "$CHANNEL" \
      --endpoint "$ENDPOINT" --app-url "$APP_URL" --token-keychain-service "$TOKEN_SERVICE"
  fi
  "$LAUNCHER_ROOT/SDA" bridge --channel "$CHANNEL" systems \
    --token-keychain-service "$TOKEN_SERVICE" --json >/dev/null
  "$LAUNCHER_ROOT/SDA" bridge --channel "$CHANNEL" context --system sda \
    --token-keychain-service "$TOKEN_SERVICE" --json >/dev/null
fi

echo "Universal Bridge ready: channel=$CHANNEL server=$ENDPOINT"
echo "Restart or open a new $CHANNEL task to load the Skill."
