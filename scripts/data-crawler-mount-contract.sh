#!/usr/bin/env sh
# Shared Data Crawler mount contract for direct Docker and Compose-compatible gates.
# Source this file, call resolve_data_crawler_mount_contract, then use
# data_crawler_docker_mount_spec with ro or rw.

resolve_data_crawler_mount_contract() {
  require_bind_directory=${1:-false}
  case "$require_bind_directory" in true|false) ;; *) echo "data_crawler_mount_require_bind_directory_invalid" >&2; return 2 ;; esac

  mount_type=${DATA_CRAWLER_MOUNT_TYPE:-}
  mount_source=${DATA_CRAWLER_MOUNT_SOURCE:-}
  legacy_volume=${DATA_CRAWLER_SHARED_VOLUME:-}

  if test -z "$mount_type" && test -z "$mount_source" && test -n "$legacy_volume"; then
    mount_type=volume
    mount_source=$legacy_volume
  fi
  test -n "$mount_type" || { echo "DATA_CRAWLER_MOUNT_TYPE is required (bind or volume)" >&2; return 2; }
  test -n "$mount_source" || { echo "DATA_CRAWLER_MOUNT_SOURCE is required" >&2; return 2; }

  case "$mount_type" in
    volume)
      case "$mount_source" in
        [A-Za-z0-9]*) ;;
        *) echo "DATA_CRAWLER_MOUNT_SOURCE must be a Docker volume name when type=volume" >&2; return 2 ;;
      esac
      case "$mount_source" in
        *[!A-Za-z0-9_.-]*) echo "DATA_CRAWLER_MOUNT_SOURCE must be a Docker volume name when type=volume" >&2; return 2 ;;
      esac
      test "${#mount_source}" -le 128 || { echo "DATA_CRAWLER_MOUNT_SOURCE volume name is too long" >&2; return 2; }
      ;;
    bind)
      case "$mount_source" in
        /*) ;;
        *) echo "DATA_CRAWLER_MOUNT_SOURCE must be an absolute host directory when type=bind" >&2; return 2 ;;
      esac
      test "$mount_source" != / || { echo "DATA_CRAWLER_MOUNT_SOURCE cannot be the host root" >&2; return 2; }
      case "$mount_source" in
        *,*|*"
"*) echo "DATA_CRAWLER_MOUNT_SOURCE contains unsupported characters" >&2; return 2 ;;
      esac
      case "$mount_source" in
        *//*|*/../*|*/./*|*/..|*/.|*/) echo "DATA_CRAWLER_MOUNT_SOURCE must be normalized" >&2; return 2 ;;
      esac
      if test "$require_bind_directory" = true; then
        test -d "$mount_source" || { echo "DATA_CRAWLER_MOUNT_SOURCE bind directory is unavailable" >&2; return 2; }
      fi
      ;;
    *) echo "DATA_CRAWLER_MOUNT_TYPE must be exactly bind or volume" >&2; return 2 ;;
  esac

  if test -n "$legacy_volume"; then
    test "$mount_type" = volume && test "$mount_source" = "$legacy_volume" || {
      echo "DATA_CRAWLER_SHARED_VOLUME conflicts with DATA_CRAWLER_MOUNT_TYPE/SOURCE" >&2
      return 2
    }
  fi

  DATA_CRAWLER_MOUNT_TYPE=$mount_type
  DATA_CRAWLER_MOUNT_SOURCE=$mount_source
  export DATA_CRAWLER_MOUNT_TYPE DATA_CRAWLER_MOUNT_SOURCE
}

data_crawler_docker_mount_spec() {
  access=${1:-}
  case "$access" in
    ro) access_suffix=,readonly ;;
    rw) access_suffix= ;;
    *) echo "data_crawler_mount_access_must_be_ro_or_rw" >&2; return 2 ;;
  esac
  case "${DATA_CRAWLER_MOUNT_TYPE:-}" in
    bind)
      printf 'type=bind,src=%s,dst=/app/data%s\n' "$DATA_CRAWLER_MOUNT_SOURCE" "$access_suffix"
      ;;
    volume)
      printf 'type=volume,src=%s,dst=/app/data%s,volume-nocopy\n' "$DATA_CRAWLER_MOUNT_SOURCE" "$access_suffix"
      ;;
    *) echo "resolve_data_crawler_mount_contract must run first" >&2; return 2 ;;
  esac
}
