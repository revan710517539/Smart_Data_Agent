#!/usr/bin/env bash
set -euo pipefail
umask 077

cd "$(dirname "${BASH_SOURCE[0]}")/.."
. scripts/data-crawler-mount-contract.sh

action=${1:-}
case "$action" in validate|preflight|migrate|create-candidate) ;;
  *) echo "usage: $0 validate|preflight|migrate|create-candidate" >&2; exit 2 ;;
esac

require_value() {
  local name=$1 value=${!1:-}
  test -n "$value" || { echo "$name is required" >&2; exit 2; }
}

read_env_value() {
  local name=$1
  awk -v key="$name" '
    index($0, key "=") == 1 { count += 1; value = substr($0, length(key) + 2) }
    END { if (count == 1) print value; else exit 1 }
  ' "$SMART_DATA_AGENT_SERVER_ENV_FILE"
}

require_env_value SMART_DATA_AGENT_SERVER_ENV_FILE
case "$SMART_DATA_AGENT_SERVER_ENV_FILE" in /*) ;; *) echo "SMART_DATA_AGENT_SERVER_ENV_FILE must be absolute" >&2; exit 2 ;; esac
test -r "$SMART_DATA_AGENT_SERVER_ENV_FILE" || { echo "SMART_DATA_AGENT_SERVER_ENV_FILE is unreadable" >&2; exit 2; }

for pair in \
  SMART_DATA_AGENT_ENV:development \
  SMART_DATA_AGENT_AUTH_MODE:development \
  SMART_DATA_AGENT_AUTO_MIGRATE:false \
  SMART_DATA_AGENT_DATA_WAREHOUSE:csv \
  SMART_DATA_AGENT_DATA_CRAWLER_ROOT:/app/data \
  SMART_DATA_AGENT_DATA_CRAWLER_MANIFEST:/app/data/manifest.json \
  SMART_DATA_AGENT_EMBEDDED_WORKER:true \
  SMART_DATA_AGENT_OBJECT_STORE:local \
  SMART_DATA_AGENT_SECRET_PROVIDER:local \
  SMART_DATA_AGENT_ALLOW_HTTP_MODEL_EGRESS:false \
  SMART_DATA_AGENT_STATIC_ROOT:/app/dist
do
  key=${pair%%:*}
  expected=${pair#*:}
  actual=$(read_env_value "$key") || { echo "$key must occur exactly once in the server env file" >&2; exit 2; }
  test "$actual" = "$expected" || { echo "$key must be exactly $expected for the Development server profile" >&2; exit 2; }
done
for key in SMART_DATA_AGENT_WSS_ENABLED SMART_DATA_AGENT_ASR_ENABLED; do
  actual=$(read_env_value "$key") || { echo "$key must occur exactly once in the server env file" >&2; exit 2; }
  case "$actual" in true|false) ;; *) echo "$key must be exactly true or false" >&2; exit 2 ;; esac
done
wss_enabled=$(read_env_value SMART_DATA_AGENT_WSS_ENABLED)
asr_enabled=$(read_env_value SMART_DATA_AGENT_ASR_ENABLED)
test "$asr_enabled" != true || test "$wss_enabled" = true || {
  echo "SMART_DATA_AGENT_ASR_ENABLED=true requires SMART_DATA_AGENT_WSS_ENABLED=true" >&2
  exit 2
}
public_origin=$(read_env_value SMART_DATA_AGENT_PUBLIC_ORIGIN) || { echo "SMART_DATA_AGENT_PUBLIC_ORIGIN must occur exactly once" >&2; exit 2; }
case "$public_origin" in http://*|https://*) ;; *) echo "SMART_DATA_AGENT_PUBLIC_ORIGIN must be an absolute HTTP(S) origin" >&2; exit 2 ;; esac
origin_authority=${public_origin#*://}
case "$origin_authority" in ''|*/*|*\?*|*\#*) echo "SMART_DATA_AGENT_PUBLIC_ORIGIN must not contain a path, query or fragment" >&2; exit 2 ;; esac
cors_origins=$(read_env_value SMART_DATA_AGENT_CORS_ORIGINS) || { echo "SMART_DATA_AGENT_CORS_ORIGINS must occur exactly once" >&2; exit 2; }
printf '%s\n' "$cors_origins" | tr ',' '\n' | grep -Fxq "$public_origin" || {
  echo "SMART_DATA_AGENT_CORS_ORIGINS must include SMART_DATA_AGENT_PUBLIC_ORIGIN" >&2
  exit 2
}
auth_secret=$(read_env_value SMART_DATA_AGENT_AUTH_SECRET) || { echo "SMART_DATA_AGENT_AUTH_SECRET must occur exactly once" >&2; exit 2; }
test "${#auth_secret}" -ge 32 || { echo "SMART_DATA_AGENT_AUTH_SECRET must contain at least 32 characters" >&2; exit 2; }
development_password=$(read_env_value SMART_DATA_AGENT_DEVELOPMENT_LOGIN_PASSWORD) || { echo "SMART_DATA_AGENT_DEVELOPMENT_LOGIN_PASSWORD must occur exactly once" >&2; exit 2; }
test -n "$development_password" || { echo "SMART_DATA_AGENT_DEVELOPMENT_LOGIN_PASSWORD must be configured" >&2; exit 2; }
database_url=$(read_env_value SMART_DATA_AGENT_DATABASE_URL) || { echo "SMART_DATA_AGENT_DATABASE_URL must occur exactly once" >&2; exit 2; }
case "$database_url" in mysql://*|mysql+pymysql://*) ;; *) echo "SMART_DATA_AGENT_DATABASE_URL must use MySQL" >&2; exit 2 ;; esac
mysql_tls_mode=$(read_env_value SMART_DATA_AGENT_MYSQL_TLS_MODE) || { echo "SMART_DATA_AGENT_MYSQL_TLS_MODE must occur exactly once" >&2; exit 2; }
case "$mysql_tls_mode" in required|verify_ca|verify_identity) ;; *) echo "SMART_DATA_AGENT_MYSQL_TLS_MODE must be required, verify_ca or verify_identity" >&2; exit 2 ;; esac
database_query="&${database_url#*\?}&"
case "$database_query" in *"&ssl_mode=$mysql_tls_mode&"*) ;; *) echo "SMART_DATA_AGENT_DATABASE_URL ssl_mode must match SMART_DATA_AGENT_MYSQL_TLS_MODE" >&2; exit 2 ;; esac
mysql_ca_mount_required=false
case "$mysql_tls_mode" in
  required)
    case "$database_query" in *"&ssl_ca="*) echo "ssl_mode=required must not claim CA verification; use verify_ca or verify_identity" >&2; exit 2 ;; esac
    ;;
  verify_ca|verify_identity)
    case "$database_query" in *"&ssl_ca=/run/secrets/mysql_ca.pem&"*) ;; *) echo "verified MySQL TLS must use /run/secrets/mysql_ca.pem" >&2; exit 2 ;; esac
    mysql_ca_mount_required=true
    ;;
esac

require_value SMART_DATA_AGENT_IMAGE
require_value SMART_DATA_AGENT_COMMIT_SHA
require_value SMART_DATA_AGENT_TARGET_PLATFORM
require_value SMART_DATA_AGENT_CONTAINER_NAME
require_value SMART_DATA_AGENT_HTTP_BIND
require_value SMART_DATA_AGENT_HTTP_PORT
case "$SMART_DATA_AGENT_COMMIT_SHA" in *[!0-9a-f]*|'') echo "SMART_DATA_AGENT_COMMIT_SHA must be a full lowercase SHA" >&2; exit 2 ;; esac
test "${#SMART_DATA_AGENT_COMMIT_SHA}" -eq 40 || { echo "SMART_DATA_AGENT_COMMIT_SHA must contain 40 characters" >&2; exit 2; }
case "$SMART_DATA_AGENT_TARGET_PLATFORM" in linux/amd64|linux/arm64) ;; *) echo "SMART_DATA_AGENT_TARGET_PLATFORM is invalid" >&2; exit 2 ;; esac
case "$SMART_DATA_AGENT_IMAGE" in
  *@sha256:*|sha256:*) ;;
  *) echo "SMART_DATA_AGENT_IMAGE must be an immutable repository digest or exact Image ID" >&2; exit 2 ;;
esac
case "$SMART_DATA_AGENT_CONTAINER_NAME" in
  [A-Za-z0-9][A-Za-z0-9_.-]*) ;;
  *) echo "SMART_DATA_AGENT_CONTAINER_NAME is invalid" >&2; exit 2 ;;
esac
case "$SMART_DATA_AGENT_CONTAINER_NAME" in *[!A-Za-z0-9_.-]*) echo "SMART_DATA_AGENT_CONTAINER_NAME is invalid" >&2; exit 2 ;; esac
case "$SMART_DATA_AGENT_HTTP_BIND" in *[!A-Za-z0-9_.-]*|'') echo "SMART_DATA_AGENT_HTTP_BIND is invalid" >&2; exit 2 ;; esac
test "$SMART_DATA_AGENT_HTTP_BIND" != 0.0.0.0 || { echo "Development server HTTP binding must not be public 0.0.0.0" >&2; exit 2; }
case "$SMART_DATA_AGENT_HTTP_PORT" in *[!0-9]*|'') echo "SMART_DATA_AGENT_HTTP_PORT is invalid" >&2; exit 2 ;; esac
test "$SMART_DATA_AGENT_HTTP_PORT" -ge 1 && test "$SMART_DATA_AGENT_HTTP_PORT" -le 65535 || { echo "SMART_DATA_AGENT_HTTP_PORT is invalid" >&2; exit 2; }
if test "$mysql_ca_mount_required" = true; then
  require_value SMART_DATA_AGENT_MYSQL_CA_HOST_PATH
  case "$SMART_DATA_AGENT_MYSQL_CA_HOST_PATH" in
    /*) ;;
    *) echo "SMART_DATA_AGENT_MYSQL_CA_HOST_PATH must be absolute" >&2; exit 2 ;;
  esac
  case "$SMART_DATA_AGENT_MYSQL_CA_HOST_PATH" in
    *,*|*$'\n'*) echo "SMART_DATA_AGENT_MYSQL_CA_HOST_PATH contains unsupported characters" >&2; exit 2 ;;
    *//*|*/../*|*/./*|*/..|*/.|*/) echo "SMART_DATA_AGENT_MYSQL_CA_HOST_PATH must be normalized" >&2; exit 2 ;;
  esac
  test -f "$SMART_DATA_AGENT_MYSQL_CA_HOST_PATH" && test -r "$SMART_DATA_AGENT_MYSQL_CA_HOST_PATH" || {
    echo "SMART_DATA_AGENT_MYSQL_CA_HOST_PATH must be a readable file" >&2
    exit 2
  }
fi

command -v docker >/dev/null 2>&1 || { echo "Docker is required" >&2; exit 2; }
docker image inspect "$SMART_DATA_AGENT_IMAGE" >/dev/null
image_id=$(docker image inspect "$SMART_DATA_AGENT_IMAGE" --format '{{.Id}}')
image_platform=$(docker image inspect "$SMART_DATA_AGENT_IMAGE" --format '{{.Os}}/{{.Architecture}}')
image_revision=$(docker image inspect "$SMART_DATA_AGENT_IMAGE" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')
test "$image_platform" = "$SMART_DATA_AGENT_TARGET_PLATFORM" || { echo "server_development_image_platform_mismatch" >&2; exit 1; }
test "$image_revision" = "$SMART_DATA_AGENT_COMMIT_SHA" || { echo "server_development_image_revision_mismatch" >&2; exit 1; }
if [[ "$SMART_DATA_AGENT_IMAGE" == sha256:* ]]; then
  test "$SMART_DATA_AGENT_IMAGE" = "$image_id" || { echo "server_development_image_id_mismatch" >&2; exit 1; }
else
  docker image inspect "$SMART_DATA_AGENT_IMAGE" --format '{{json .RepoDigests}}' | grep -Fq "\"$SMART_DATA_AGENT_IMAGE\"" || {
    echo "server_development_image_digest_mismatch" >&2
    exit 1
  }
fi

resolve_data_crawler_mount_contract true
data_mount_spec=$(data_crawler_docker_mount_spec ro)

state_mount_spec() {
  local label=$1 type=$2 source=$3 destination=$4
  test -n "$type" && test -n "$source" || { echo "${label}_mount_type_and_source_are_required" >&2; exit 2; }
  case "$type" in
    volume)
      [[ "$source" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]] || { echo "${label}_volume_name_invalid" >&2; exit 2; }
      # Runtime/Topic volumes intentionally use Docker's first-mount copy-up.
      # The image owns these directories as app:app; volume-nocopy would leave
      # a new volume root-owned and make the non-root application fail writes.
      printf 'type=volume,src=%s,dst=%s' "$source" "$destination"
      ;;
    bind)
      [[ "$source" == /* && "$source" != / && "$source" != *","* && "$source" != *"//"* && "$source" != *"/../"* && "$source" != *"/./"* && "$source" != */.. && "$source" != */. && "$source" != */ ]] || { echo "${label}_bind_source_invalid" >&2; exit 2; }
      test -d "$source" || { echo "${label}_bind_source_unavailable" >&2; exit 2; }
      printf 'type=bind,src=%s,dst=%s' "$source" "$destination"
      ;;
    *) echo "${label}_mount_type_invalid" >&2; exit 2 ;;
  esac
}

runtime_mount_spec=$(state_mount_spec runtime "${SMART_DATA_AGENT_RUNTIME_MOUNT_TYPE:-}" "${SMART_DATA_AGENT_RUNTIME_MOUNT_SOURCE:-}" /app/runtime)
topic_mount_spec=$(state_mount_spec topic_data "${SMART_DATA_AGENT_TOPIC_DATA_MOUNT_TYPE:-}" "${SMART_DATA_AGENT_TOPIC_DATA_MOUNT_SOURCE:-}" /app/Topic_Data)

common_args=(
  --platform "$SMART_DATA_AGENT_TARGET_PLATFORM"
  --env-file "$SMART_DATA_AGENT_SERVER_ENV_FILE"
  --env "SMART_DATA_AGENT_ENV=development"
  --env "SMART_DATA_AGENT_AUTH_MODE=development"
  --env "SMART_DATA_AGENT_AUTO_MIGRATE=false"
  --env "SMART_DATA_AGENT_EMBEDDED_WORKER=true"
  --env "SMART_DATA_AGENT_DATA_WAREHOUSE=csv"
  --env "SMART_DATA_AGENT_DATA_CRAWLER_ROOT=/app/data"
  --env "SMART_DATA_AGENT_IMAGE_REFERENCE=$SMART_DATA_AGENT_IMAGE"
  --env "SMART_DATA_AGENT_RUNTIME_INSTANCE_ID=$SMART_DATA_AGENT_CONTAINER_NAME"
  --mount "$data_mount_spec"
  --mount "$runtime_mount_spec"
  --mount "$topic_mount_spec"
  --read-only
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=268435456
  --security-opt no-new-privileges
  --cap-drop ALL
  --init
)
if test "$mysql_ca_mount_required" = true; then
  common_args+=(--mount "type=bind,src=$SMART_DATA_AGENT_MYSQL_CA_HOST_PATH,dst=/run/secrets/mysql_ca.pem,readonly")
fi
if test -n "${SMART_DATA_AGENT_DOCKER_NETWORK:-}"; then
  common_args+=(--network "$SMART_DATA_AGENT_DOCKER_NETWORK")
fi

if test "$action" = validate; then
  printf '%s\n' "server development contract valid image_id=$image_id platform=$image_platform mount_type=$DATA_CRAWLER_MOUNT_TYPE mysql_tls_mode=$mysql_tls_mode"
  exit 0
fi

if test "$action" = preflight; then
  docker run --rm "${common_args[@]}" "$SMART_DATA_AGENT_IMAGE" python -c '
import json, os
from pathlib import Path
from backend.platform.runtime_config import load_runtime_config
config = load_runtime_config()
assert config.environment == "development"
assert config.auth_mode == "development"
assert config.auto_migrate is False
assert config.embedded_worker_enabled is True
assert Path("/app/data/manifest.json").is_file(), "data_crawler_manifest_missing"
assert os.access("/app/data/manifest.json", os.R_OK), "data_crawler_manifest_unreadable"
assert os.access("/app/runtime", os.W_OK), "runtime_mount_not_writable"
assert os.access("/app/Topic_Data", os.W_OK), "topic_data_mount_not_writable"
print(json.dumps({"status":"passed","environment":config.environment,"auth_mode":config.auth_mode,"embedded_worker":config.embedded_worker_enabled}, sort_keys=True))
'
  exit 0
fi

require_value SMART_DATA_AGENT_DB_BACKUP_RECEIPT
require_value SMART_DATA_AGENT_DB_BACKUP_MAX_AGE_SECONDS
case "$SMART_DATA_AGENT_DB_BACKUP_MAX_AGE_SECONDS" in *[!0-9]*|'') echo "SMART_DATA_AGENT_DB_BACKUP_MAX_AGE_SECONDS is invalid" >&2; exit 2 ;; esac
test "$SMART_DATA_AGENT_DB_BACKUP_MAX_AGE_SECONDS" -ge 300 && test "$SMART_DATA_AGENT_DB_BACKUP_MAX_AGE_SECONDS" -le 604800 || {
  echo "SMART_DATA_AGENT_DB_BACKUP_MAX_AGE_SECONDS must be between 300 and 604800" >&2
  exit 2
}
case "$SMART_DATA_AGENT_DB_BACKUP_RECEIPT" in /*) ;; *) echo "SMART_DATA_AGENT_DB_BACKUP_RECEIPT must be absolute" >&2; exit 2 ;; esac
test -r "$SMART_DATA_AGENT_DB_BACKUP_RECEIPT" || { echo "SMART_DATA_AGENT_DB_BACKUP_RECEIPT is unreadable" >&2; exit 2; }
backup_dir=$(dirname "$SMART_DATA_AGENT_DB_BACKUP_RECEIPT")
backup_name=$(basename "$SMART_DATA_AGENT_DB_BACKUP_RECEIPT")
case "$backup_dir" in *,*) echo "SMART_DATA_AGENT_DB_BACKUP_RECEIPT directory contains unsupported characters" >&2; exit 2 ;; esac
docker run --rm --platform "$SMART_DATA_AGENT_TARGET_PLATFORM" \
  --mount "type=bind,src=$backup_dir,dst=/release-backup,readonly" \
  "$SMART_DATA_AGENT_IMAGE" \
  python /app/scripts/mysql_backup_receipt.py verify "/release-backup/$backup_name" \
    --max-age-seconds "$SMART_DATA_AGENT_DB_BACKUP_MAX_AGE_SECONDS"

require_value SMART_DATA_AGENT_MIGRATION_RECEIPT_DIR
test -d "$SMART_DATA_AGENT_MIGRATION_RECEIPT_DIR" && test -w "$SMART_DATA_AGENT_MIGRATION_RECEIPT_DIR" || {
  echo "SMART_DATA_AGENT_MIGRATION_RECEIPT_DIR must be an existing writable directory" >&2
  exit 2
}
migration_receipt="$SMART_DATA_AGENT_MIGRATION_RECEIPT_DIR/migration-$SMART_DATA_AGENT_COMMIT_SHA.json"

verify_migration_receipt() {
  local receipt=$1 receipt_dir receipt_name
  receipt_dir=$(dirname "$receipt")
  receipt_name=$(basename "$receipt")
  case "$receipt_dir" in /*) ;; *) echo "migration receipt directory must be absolute" >&2; exit 2 ;; esac
  case "$receipt_dir" in *,*|*$'\n'*|*$'\r'*) echo "migration receipt directory contains unsupported characters" >&2; exit 2 ;; esac
  docker run --rm --platform "$SMART_DATA_AGENT_TARGET_PLATFORM" \
    --mount "type=bind,src=$receipt_dir,dst=/release-receipts,readonly" \
    "$SMART_DATA_AGENT_IMAGE" \
    python /app/scripts/mysql_migration_receipt.py verify "/release-receipts/$receipt_name" \
      --commit-sha "$SMART_DATA_AGENT_COMMIT_SHA"
}

if test "$action" = migrate; then
  test ! -e "$migration_receipt" || { echo "migration receipt already exists" >&2; exit 2; }
  temporary_receipt=$(mktemp "$SMART_DATA_AGENT_MIGRATION_RECEIPT_DIR/.migration-$SMART_DATA_AGENT_COMMIT_SHA.XXXXXX")
  cleanup_receipt() { rm -f "$temporary_receipt"; }
  trap cleanup_receipt EXIT
  if docker run --rm "${common_args[@]}" "$SMART_DATA_AGENT_IMAGE" python /app/scripts/migrate_mysql.py >"$temporary_receipt"; then
    verify_migration_receipt "$temporary_receipt"
    mv "$temporary_receipt" "$migration_receipt"
    trap - EXIT
    cat "$migration_receipt"
    exit 0
  fi
  echo "server development migration failed" >&2
  exit 1
fi

test -s "$migration_receipt" || { echo "exact revision migration receipt is required before container creation" >&2; exit 2; }
verify_migration_receipt "$migration_receipt"
if docker container inspect "$SMART_DATA_AGENT_CONTAINER_NAME" >/dev/null 2>&1; then
  echo "exact candidate container already exists; preserve it and choose an explicit new name" >&2
  exit 2
fi
docker create --name "$SMART_DATA_AGENT_CONTAINER_NAME" \
  "${common_args[@]}" \
  --restart no \
  --publish "$SMART_DATA_AGENT_HTTP_BIND:$SMART_DATA_AGENT_HTTP_PORT:8787" \
  "$SMART_DATA_AGENT_IMAGE" >/dev/null
created_image=$(docker container inspect "$SMART_DATA_AGENT_CONTAINER_NAME" --format '{{.Image}}')
test "$created_image" = "$image_id" || { echo "created candidate image ID mismatch" >&2; exit 1; }
printf '%s\n' "candidate container created name=$SMART_DATA_AGENT_CONTAINER_NAME image_id=$image_id restart_owner=systemd; it remains stopped until the approved start step"
