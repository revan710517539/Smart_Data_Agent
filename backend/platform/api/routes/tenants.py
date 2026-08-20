from __future__ import annotations

from typing import Any

from backend.authz import normalize_tenant_id
from backend.authz.seed import OPERATING_TENANTS
from backend.platform.api.support import send_route_exception


def handle_tenants_get(handler: Any, query: str) -> None:
    try:
        tenants = _active_tenants(handler)
        handler._send_json({"tenants": tenants, "count": len(tenants)})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def _active_tenants(handler: Any) -> list[dict[str, str]]:
    """Return the active login catalog from the runtime's tenant authority.

    Local SQLite development has no relational tenant catalog and keeps the
    source-controlled operating list. Relational deployments must expose only
    actually provisioned tenants; otherwise the login page can offer a tenant
    that the same database will reject during session creation.
    """

    pool = getattr(handler.services, "primary_database_pool", None)
    if pool is None:
        return [
            {
                "id": normalize_tenant_id(name),
                "name": name,
                "status": "active",
            }
            for name in OPERATING_TENANTS
        ]

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
    return [
        {
            "id": tenant_code,
            "name": tenant_name,
            "status": str(_row_value(row, "status", 2)),
        }
        for row in rows
        if _is_login_catalog_tenant(
            tenant_code := str(_row_value(row, "tenant_code", 0)),
            tenant_name := str(_row_value(row, "tenant_name", 1)),
        )
    ]


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


def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]
