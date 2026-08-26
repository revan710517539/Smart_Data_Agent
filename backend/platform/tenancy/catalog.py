from __future__ import annotations

from typing import Any

from backend.authz import SUPER_ADMIN_ROLE_ID, SUPER_ADMIN_USER_ID, build_default_rbac_seed, normalize_tenant_id
from backend.authz.seed import OPERATING_TENANTS
from backend.platform.database.identity import PostgreSQLIdentityResolver


RESERVED_TENANT_NAMES = frozenset(
    {
        "全部机构",
        "演示机构",
        "sda-internal",
        "SDA 内部环境",
        "tenant_demo",
        "__global__",
    }
)
SQLITE_CATALOG_TABLE = "platform_operating_tenants"
_MAX_TENANT_NAME_LENGTH = 50


def list_active_tenants(services: Any) -> list[dict[str, str]]:
    """Return the login/selector catalog for the current runtime."""

    pool = getattr(services, "primary_database_pool", None)
    if pool is not None:
        return _list_relational_tenants(pool)
    sqlite_rows = _list_sqlite_tenants(services)
    if sqlite_rows is not None:
        return sqlite_rows
    memory = _memory_catalog(services)
    if memory is not None:
        return [
            _public_tenant(item["id"], item["name"], item.get("status") or "active")
            for item in memory
            if str(item.get("status") or "active") == "active"
            and _is_login_catalog_tenant(item["id"], item["name"])
        ]
    return [_public_tenant(normalize_tenant_id(name), name, "active") for name in OPERATING_TENANTS]


def catalog_tenant_ids(services: Any) -> tuple[str, ...]:
    return tuple(item["id"] for item in list_active_tenants(services))


def catalog_tenant_names(services: Any) -> tuple[str, ...]:
    return tuple(item["name"] for item in list_active_tenants(services))


def create_tenant(services: Any, name: str, *, actor_user_id: str = SUPER_ADMIN_USER_ID) -> dict[str, str]:
    tenant_name = normalize_tenant_name(name)
    tenant_id = normalize_tenant_id(tenant_name)
    existing = _find_catalog_record(services, tenant_id, tenant_name)
    if existing and str(existing.get("status") or "active") == "active":
        raise ValueError("tenant_name_duplicate")
    if existing:
        scope_service = getattr(services, "tenant_scope_service", None)
        if scope_service is not None:
            scope_service.revoke_tenant_scope(tenant_id, actor_user_id, "tenant_reactivated_scope_reset")
    saved = _upsert_catalog_record(services, tenant_id, tenant_name, reactivate=bool(existing))
    _seed_tenant_default_roles(services, tenant_name)
    _seed_tenant_runtime_defaults(services, tenant_id)
    return saved


def update_tenant(services: Any, tenant_id: str, name: str) -> dict[str, str]:
    current_id = _require_tenant_id(tenant_id)
    tenant_name = normalize_tenant_name(name)
    current = _require_active_record(services, current_id)
    if tenant_name != current["name"]:
        duplicate = _find_catalog_record(services, normalize_tenant_id(tenant_name), tenant_name)
        if duplicate and duplicate["id"] != current_id and str(duplicate.get("status") or "active") == "active":
            raise ValueError("tenant_name_duplicate")
    return _rename_catalog_record(services, current_id, tenant_name)


def delete_tenant(services: Any, tenant_id: str, *, actor_user_id: str = SUPER_ADMIN_USER_ID) -> dict[str, str]:
    current_id = _require_tenant_id(tenant_id)
    current = _require_active_record(services, current_id)
    closed = _close_catalog_record(services, current_id)
    _unseed_tenant_roles(services, current_id)
    scope_service = getattr(services, "tenant_scope_service", None)
    if scope_service is not None:
        scope_service.revoke_tenant_scope(current_id, actor_user_id, "tenant_closed")
    return closed or {**current, "status": "closed"}


def normalize_tenant_name(raw: str) -> str:
    name = str(raw or "").strip()
    if name.startswith("tenant:"):
        name = name[len("tenant:") :].strip()
    if not name:
        raise ValueError("tenant_name_required")
    if len(name) > _MAX_TENANT_NAME_LENGTH:
        raise ValueError("tenant_name_too_long")
    if name in RESERVED_TENANT_NAMES or name.startswith(("account:", "system:")):
        raise ValueError("tenant_name_reserved")
    if any(character in name for character in "/\\\n\r\t"):
        raise ValueError("tenant_name_invalid")
    return name


def is_login_catalog_tenant(tenant_code: str, tenant_name: str) -> bool:
    return _is_login_catalog_tenant(tenant_code, tenant_name)


def _require_tenant_id(tenant_id: str) -> str:
    current_id = str(tenant_id or "").strip()
    if not current_id:
        raise ValueError("tenant_id_required")
    if current_id.startswith("tenant:"):
        return current_id
    return normalize_tenant_id(current_id)


def _require_active_record(services: Any, tenant_id: str) -> dict[str, str]:
    record = _find_catalog_record(services, tenant_id, "")
    if record is None or str(record.get("status") or "active") != "active" or not _is_login_catalog_tenant(
        record["id"], record["name"]
    ):
        raise ValueError("tenant_not_found")
    return _public_tenant(record["id"], record["name"], "active")


def _find_catalog_record(services: Any, tenant_id: str, tenant_name: str) -> dict[str, str] | None:
    wanted_ids = {item for item in (str(tenant_id or "").strip(),) if item}
    wanted_names = {item for item in (str(tenant_name or "").strip(),) if item}
    pool = getattr(services, "primary_database_pool", None)
    if pool is not None:
        return _find_relational_record(pool, wanted_ids, wanted_names)
    sqlite_rows = _list_sqlite_tenants(services, include_inactive=True)
    if sqlite_rows is not None:
        return _match_record(sqlite_rows, wanted_ids, wanted_names)
    memory = _memory_catalog(services)
    if memory is not None:
        return _match_record(memory, wanted_ids, wanted_names)
    defaults = [
        _public_tenant(normalize_tenant_id(name), name, "active")
        for name in OPERATING_TENANTS
    ]
    return _match_record(defaults, wanted_ids, wanted_names)


def _match_record(
    records: list[dict[str, str]],
    wanted_ids: set[str],
    wanted_names: set[str],
) -> dict[str, str] | None:
    for item in records:
        if item["id"] in wanted_ids or item["name"] in wanted_names:
            return item
    return None


def _upsert_catalog_record(services: Any, tenant_id: str, tenant_name: str, *, reactivate: bool) -> dict[str, str]:
    pool = getattr(services, "primary_database_pool", None)
    if pool is not None:
        return _upsert_relational_record(pool, tenant_id, tenant_name, reactivate=reactivate)
    if _sqlite_connection(services) is not None:
        return _upsert_sqlite_record(services, tenant_id, tenant_name, reactivate=reactivate)
    return _upsert_memory_record(services, tenant_id, tenant_name, reactivate=reactivate)


def _rename_catalog_record(services: Any, tenant_id: str, tenant_name: str) -> dict[str, str]:
    pool = getattr(services, "primary_database_pool", None)
    if pool is not None:
        return _rename_relational_record(pool, tenant_id, tenant_name)
    if _sqlite_connection(services) is not None:
        return _rename_sqlite_record(services, tenant_id, tenant_name)
    return _rename_memory_record(services, tenant_id, tenant_name)


def _close_catalog_record(services: Any, tenant_id: str) -> dict[str, str]:
    pool = getattr(services, "primary_database_pool", None)
    if pool is not None:
        return _close_relational_record(pool, tenant_id)
    if _sqlite_connection(services) is not None:
        return _close_sqlite_record(services, tenant_id)
    return _close_memory_record(services, tenant_id)


def _seed_tenant_default_roles(services: Any, tenant_name: str) -> None:
    repository = _policy_repository(services)
    if repository is None:
        return
    seed = build_default_rbac_seed([tenant_name])
    tenant_id = normalize_tenant_id(tenant_name)
    roles = [role for role in seed.roles if role.tenant_id == tenant_id]
    policies = [policy for policy in seed.policies if policy.tenant_id == tenant_id]
    assignments = [item for item in seed.assignments if item.tenant_id == tenant_id]
    manageable = {
        role_id: set(targets)
        for role_id, targets in seed.manageable_roles.items()
        if role_id != SUPER_ADMIN_ROLE_ID
    }
    repository.seed(roles, assignments, policies, manageable)
    extra = set(seed.manageable_roles.get(SUPER_ADMIN_ROLE_ID) or ())
    if extra:
        existing = set(repository.get_manageable_role_ids(SUPER_ADMIN_ROLE_ID))
        repository.replace_manageable_role_ids(SUPER_ADMIN_ROLE_ID, existing | extra)


def _seed_tenant_runtime_defaults(services: Any, tenant_id: str) -> None:
    store = getattr(services, "data_asset_store", None)
    seeder = getattr(store, "seed_missing_defaults", None)
    if not callable(seeder):
        return
    try:
        seeder(tenant_id, updated_by=SUPER_ADMIN_USER_ID)
    except TypeError:
        seeder(tenant_id)
    except Exception:
        return


def _unseed_tenant_roles(services: Any, tenant_id: str) -> None:
    repository = _policy_repository(services)
    if repository is None:
        return
    roles = [role for role in repository.list_roles(tenant_id) if role.tenant_id == tenant_id]
    role_ids = {role.role_id for role in roles}
    if role_ids:
        existing = set(repository.get_manageable_role_ids(SUPER_ADMIN_ROLE_ID))
        if existing & role_ids:
            repository.replace_manageable_role_ids(SUPER_ADMIN_ROLE_ID, existing - role_ids)
    for role in roles:
        repository.delete_role(role.role_id)


def _policy_repository(services: Any) -> Any | None:
    broker = getattr(services, "permission_broker", None)
    enforcer = getattr(broker, "enforcer", None) if broker is not None else None
    return getattr(enforcer, "repository", None)


def _list_relational_tenants(pool: Any) -> list[dict[str, str]]:
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tenant_code, tenant_name, status
                FROM platform_tenants
                WHERE status = 'active' AND tenant_code NOT IN (%s, %s)
                ORDER BY tenant_name, tenant_code
                """,
                ("__global__", "tenant:sda-internal"),
            )
            rows = cursor.fetchall()
    tenants: list[dict[str, str]] = []
    for row in rows:
        tenant_code = str(_row_value(row, "tenant_code", 0))
        tenant_name = str(_row_value(row, "tenant_name", 1))
        status = str(_row_value(row, "status", 2) or "active")
        if _is_login_catalog_tenant(tenant_code, tenant_name):
            tenants.append(_public_tenant(tenant_code, tenant_name, status))
    return tenants


def _find_relational_record(pool: Any, wanted_ids: set[str], wanted_names: set[str]) -> dict[str, str] | None:
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tenant_code, tenant_name, status
                FROM platform_tenants
                WHERE tenant_code = %s OR tenant_name = %s
                ORDER BY CASE WHEN status = 'active' THEN 0 ELSE 1 END, tenant_code
                """,
                (next(iter(wanted_ids), ""), next(iter(wanted_names), "")),
            )
            rows = cursor.fetchall()
    records = [
        _public_tenant(
            str(_row_value(row, "tenant_code", 0)),
            str(_row_value(row, "tenant_name", 1)),
            str(_row_value(row, "status", 2) or "active"),
        )
        for row in rows
    ]
    return _match_record(records, wanted_ids, wanted_names)


def _upsert_relational_record(pool: Any, tenant_id: str, tenant_name: str, *, reactivate: bool) -> dict[str, str]:
    def write(connection: Any) -> dict[str, str]:
        if reactivate:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_tenants
                    SET tenant_name = %s, status = 'active', updated_at = CURRENT_TIMESTAMP,
                        lock_version = lock_version + 1
                    WHERE tenant_code = %s
                    """,
                    (tenant_name, tenant_id),
                )
        PostgreSQLIdentityResolver.ensure_tenant(connection, tenant_id, tenant_name)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE platform_tenants
                SET tenant_name = %s, status = 'active'
                WHERE tenant_code = %s
                """,
                (tenant_name, tenant_id),
            )
            cursor.execute(
                """
                SELECT tenant_code, tenant_name, status
                FROM platform_tenants
                WHERE tenant_code = %s
                """,
                (tenant_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise ValueError("tenant_not_found")
        return _public_tenant(
            str(_row_value(row, "tenant_code", 0)),
            str(_row_value(row, "tenant_name", 1)),
            str(_row_value(row, "status", 2) or "active"),
        )

    return _write_pool(pool, write)


def _rename_relational_record(pool: Any, tenant_id: str, tenant_name: str) -> dict[str, str]:
    def write(connection: Any) -> dict[str, str]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE platform_tenants
                SET tenant_name = %s, updated_at = CURRENT_TIMESTAMP, lock_version = lock_version + 1
                WHERE tenant_code = %s AND status = 'active'
                """,
                (tenant_name, tenant_id),
            )
            cursor.execute(
                """
                SELECT tenant_code, tenant_name, status
                FROM platform_tenants
                WHERE tenant_code = %s
                """,
                (tenant_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise ValueError("tenant_not_found")
        return _public_tenant(
            str(_row_value(row, "tenant_code", 0)),
            str(_row_value(row, "tenant_name", 1)),
            str(_row_value(row, "status", 2) or "active"),
        )

    return _write_pool(pool, write)


def _close_relational_record(pool: Any, tenant_id: str) -> dict[str, str]:
    def write(connection: Any) -> dict[str, str]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE platform_tenants
                SET status = 'closed', updated_at = CURRENT_TIMESTAMP, lock_version = lock_version + 1
                WHERE tenant_code = %s AND status = 'active'
                """,
                (tenant_id,),
            )
            cursor.execute(
                """
                SELECT tenant_code, tenant_name, status
                FROM platform_tenants
                WHERE tenant_code = %s
                """,
                (tenant_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise ValueError("tenant_not_found")
        return _public_tenant(
            str(_row_value(row, "tenant_code", 0)),
            str(_row_value(row, "tenant_name", 1)),
            str(_row_value(row, "status", 2) or "closed"),
        )

    return _write_pool(pool, write)


def _write_pool(pool: Any, write: Any) -> dict[str, str]:
    transaction = getattr(pool, "transaction", None)
    if callable(transaction):
        with transaction() as connection:
            return write(connection)
    with pool.connection() as connection:
        try:
            result = write(connection)
            commit = getattr(connection, "commit", None)
            if callable(commit):
                commit()
            return result
        except BaseException:
            rollback = getattr(connection, "rollback", None)
            if callable(rollback):
                rollback()
            raise


def _sqlite_connection(services: Any) -> Any | None:
    repository = _policy_repository(services)
    return getattr(repository, "_conn", None)


def _list_sqlite_tenants(services: Any, *, include_inactive: bool = False) -> list[dict[str, str]] | None:
    connection = _sqlite_connection(services)
    if connection is None:
        return None
    existing = connection.execute(
        f"SELECT name FROM sqlite_master WHERE type = 'table' AND name = '{SQLITE_CATALOG_TABLE}'"
    ).fetchone()
    if existing is None:
        return None
    count_row = connection.execute(f"SELECT COUNT(*) FROM {SQLITE_CATALOG_TABLE}").fetchone()
    if int(count_row[0] if count_row is not None else 0) == 0:
        return None
    statement = f"SELECT tenant_code, tenant_name, status FROM {SQLITE_CATALOG_TABLE}"
    if not include_inactive:
        statement += " WHERE status = 'active'"
    statement += " ORDER BY tenant_name, tenant_code"
    rows = connection.execute(statement).fetchall()
    tenants: list[dict[str, str]] = []
    for row in rows:
        tenant_code = str(row[0])
        tenant_name = str(row[1])
        status = str(row[2] or "active")
        if include_inactive or _is_login_catalog_tenant(tenant_code, tenant_name):
            tenants.append(_public_tenant(tenant_code, tenant_name, status))
    return tenants


def _ensure_sqlite_catalog_seeded(services: Any) -> Any:
    connection = _sqlite_connection(services)
    if connection is None:
        raise RuntimeError("sqlite_tenant_catalog_unavailable")
    with connection:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {SQLITE_CATALOG_TABLE} (
                tenant_code TEXT PRIMARY KEY,
                tenant_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            )
            """
        )
        count_row = connection.execute(f"SELECT COUNT(*) FROM {SQLITE_CATALOG_TABLE}").fetchone()
        if int(count_row[0] if count_row is not None else 0) == 0:
            connection.executemany(
                f"INSERT INTO {SQLITE_CATALOG_TABLE}(tenant_code, tenant_name, status) VALUES (?, ?, 'active')",
                [(normalize_tenant_id(name), name) for name in OPERATING_TENANTS],
            )
    return connection


def _upsert_sqlite_record(services: Any, tenant_id: str, tenant_name: str, *, reactivate: bool) -> dict[str, str]:
    del reactivate
    connection = _ensure_sqlite_catalog_seeded(services)
    with connection:
        connection.execute(
            f"""
            INSERT INTO {SQLITE_CATALOG_TABLE}(tenant_code, tenant_name, status)
            VALUES (?, ?, 'active')
            ON CONFLICT(tenant_code) DO UPDATE SET tenant_name = excluded.tenant_name, status = 'active'
            """,
            (tenant_id, tenant_name),
        )
    return _public_tenant(tenant_id, tenant_name, "active")


def _rename_sqlite_record(services: Any, tenant_id: str, tenant_name: str) -> dict[str, str]:
    connection = _ensure_sqlite_catalog_seeded(services)
    with connection:
        cursor = connection.execute(
            f"UPDATE {SQLITE_CATALOG_TABLE} SET tenant_name = ? WHERE tenant_code = ? AND status = 'active'",
            (tenant_name, tenant_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("tenant_not_found")
    return _public_tenant(tenant_id, tenant_name, "active")


def _close_sqlite_record(services: Any, tenant_id: str) -> dict[str, str]:
    connection = _ensure_sqlite_catalog_seeded(services)
    with connection:
        row = connection.execute(
            f"SELECT tenant_name FROM {SQLITE_CATALOG_TABLE} WHERE tenant_code = ? AND status = 'active'",
            (tenant_id,),
        ).fetchone()
        if row is None:
            raise ValueError("tenant_not_found")
        connection.execute(
            f"UPDATE {SQLITE_CATALOG_TABLE} SET status = 'closed' WHERE tenant_code = ?",
            (tenant_id,),
        )
    return _public_tenant(tenant_id, str(row[0]), "closed")


def _memory_catalog(services: Any) -> list[dict[str, str]] | None:
    catalog = getattr(services, "_memory_tenant_catalog", None)
    if not isinstance(catalog, list):
        return None
    return catalog


def _ensure_memory_catalog(services: Any) -> list[dict[str, str]]:
    catalog = _memory_catalog(services)
    if catalog is None:
        catalog = [_public_tenant(normalize_tenant_id(name), name, "active") for name in OPERATING_TENANTS]
        setattr(services, "_memory_tenant_catalog", catalog)
    return catalog


def _upsert_memory_record(services: Any, tenant_id: str, tenant_name: str, *, reactivate: bool) -> dict[str, str]:
    catalog = _ensure_memory_catalog(services)
    for index, item in enumerate(catalog):
        if item["id"] == tenant_id:
            catalog[index] = _public_tenant(tenant_id, tenant_name, "active")
            return catalog[index]
    record = _public_tenant(tenant_id, tenant_name, "active")
    catalog.append(record)
    return record


def _rename_memory_record(services: Any, tenant_id: str, tenant_name: str) -> dict[str, str]:
    catalog = _ensure_memory_catalog(services)
    for index, item in enumerate(catalog):
        if item["id"] == tenant_id and item.get("status") == "active":
            catalog[index] = _public_tenant(tenant_id, tenant_name, "active")
            return catalog[index]
    raise ValueError("tenant_not_found")


def _close_memory_record(services: Any, tenant_id: str) -> dict[str, str]:
    catalog = _ensure_memory_catalog(services)
    for index, item in enumerate(catalog):
        if item["id"] == tenant_id and item.get("status") == "active":
            catalog[index] = _public_tenant(tenant_id, item["name"], "closed")
            return catalog[index]
    raise ValueError("tenant_not_found")


def _is_login_catalog_tenant(tenant_code: str, tenant_name: str) -> bool:
    code = tenant_code.strip()
    name = tenant_name.strip()
    if not code or code in {"__global__", "tenant:sda-internal", "tenant_demo"}:
        return False
    if code.startswith(("account:", "system:")):
        return False
    if name.startswith(("account:", "system:")):
        return False
    return True


def _public_tenant(tenant_id: str, tenant_name: str, status: str) -> dict[str, str]:
    return {"id": tenant_id, "name": tenant_name, "status": status}


def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]
