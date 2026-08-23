#!/usr/bin/env sh
set -eu

root=${SMART_DATA_AGENT_DATA_CRAWLER_ROOT:-/app/data}
python3 scripts/validate_data_crawler_manifest.py --root "$root" --require-read-only "$@"
