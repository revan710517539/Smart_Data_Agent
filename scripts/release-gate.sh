#!/usr/bin/env sh
set -eu

git diff --check
python3 scripts/check_production_development_standard.py
python3 scripts/check_mysql_migration_history.py
python3 scripts/check_server_deployment_contract.py
python3 scripts/check_mysql_sql_closure.py
python3 scripts/check_production_capability_pack.py
python3 scripts/generate_database_schema.py --check
python3 scripts/generate_api_client.py --check
python3 scripts/check_frontend_module_size.py
python3 -m pip_audit -r requirements.lock
npm test
test -n "${SMART_DATA_AGENT_TEST_MYSQL_URL:-}" || {
  echo "SMART_DATA_AGENT_TEST_MYSQL_URL is required for the MySQL 8.0.18 release gate" >&2
  exit 1
}
python3 -m unittest backend.platform.tests.test_mysql_stores_integration backend.platform.tests.test_mysql_sql_closure -v
printf '%s\n' "release gate passed"
