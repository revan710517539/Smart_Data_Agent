from __future__ import annotations

from typing import Any


class PostgreSQLIdentityResolver:
    """Map stable external codes used by API contracts to PostgreSQL UUID keys."""

    @staticmethod
    def tenant_id(connection: Any, tenant_code: str, *, required: bool = True) -> Any | None:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tenant_id FROM platform_tenants WHERE tenant_code = %s AND status = 'active'",
                (tenant_code,),
            )
            row = cursor.fetchone()
        if row:
            return _row_value(row, "tenant_id", 0)
        if required:
            raise KeyError("tenant_not_provisioned")
        return None

    @staticmethod
    def user_id(connection: Any, external_subject: str, *, required: bool = True) -> Any | None:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT user_id FROM platform_user_profiles WHERE external_subject = %s AND status = 'active'",
                (external_subject,),
            )
            row = cursor.fetchone()
        if row:
            return _row_value(row, "user_id", 0)
        if required:
            raise KeyError("user_not_provisioned")
        return None

    @staticmethod
    def role_id(connection: Any, role_code: str, tenant_code: str | None = None, *, required: bool = True) -> Any | None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT r.role_id
                FROM auth_roles r
                LEFT JOIN platform_tenants t ON t.tenant_id = r.tenant_id
                WHERE r.role_code = %s
                  AND (%s::varchar IS NULL OR t.tenant_code = %s OR r.tenant_id IS NULL)
                  AND r.status = 'active'
                ORDER BY CASE WHEN t.tenant_code = %s THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (role_code, tenant_code, tenant_code, tenant_code),
            )
            row = cursor.fetchone()
        if row:
            return _row_value(row, "role_id", 0)
        if required:
            raise KeyError("role_not_provisioned")
        return None

    @staticmethod
    def ensure_tenant(connection: Any, tenant_code: str, tenant_name: str | None = None) -> Any:
        existing = PostgreSQLIdentityResolver.tenant_id(connection, tenant_code, required=False)
        if existing is not None:
            return existing
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO platform_tenants(tenant_code, tenant_name, status)
                VALUES (%s, %s, 'active') RETURNING tenant_id
                """,
                (tenant_code, tenant_name or tenant_code.removeprefix("tenant:")),
            )
            row = cursor.fetchone()
        return _row_value(row, "tenant_id", 0)

    @staticmethod
    def ensure_user(
        connection: Any,
        external_subject: str,
        *,
        email: str,
        display_name: str,
        status: str = "active",
    ) -> Any:
        existing = PostgreSQLIdentityResolver.user_id(connection, external_subject, required=False)
        normalized_status = status if status in {"invited", "active", "locked", "disabled"} else "active"
        if existing is not None:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_user_profiles
                    SET email = %s, display_name = %s, status = %s,
                        updated_at = now(), lock_version = lock_version + 1
                    WHERE user_id = %s
                    """,
                    (email.lower(), display_name, normalized_status, existing),
                )
            return existing
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO platform_user_profiles(external_subject, email, display_name, status)
                VALUES (%s, %s, %s, %s) RETURNING user_id
                """,
                (external_subject, email.lower(), display_name, normalized_status),
            )
            row = cursor.fetchone()
        return _row_value(row, "user_id", 0)


def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]
