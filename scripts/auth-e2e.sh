#!/usr/bin/env sh
set -eu

if test "${SMART_DATA_AGENT_AUTH_E2E_MODE:-candidate}" = "local"; then
  exec node scripts/frontend-permission-smoke.mjs
fi
test -n "${SMART_DATA_AGENT_AUTH_E2E_URL:-}" || { echo "SMART_DATA_AGENT_AUTH_E2E_URL required" >&2; exit 2; }
test -n "${SMART_DATA_AGENT_AUTH_E2E_CHROME_PROFILE:-}" || { echo "SMART_DATA_AGENT_AUTH_E2E_CHROME_PROFILE required" >&2; exit 2; }
exec node scripts/production-auth-browser-e2e.mjs
