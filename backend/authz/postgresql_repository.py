from __future__ import annotations

import json
from collections.abc import Iterable
from contextlib import contextmanager
from typing import Any, Iterator

from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.postgresql import PostgreSQLConnectionPool

from .models import PermissionPolicy, Role, RoleAssignment, RoleLevel
from .repository import PolicyRepository


_EXTRA_POLICY_ATTRS = "__policy_attrs"


class PostgreSQLPolicyRepository(PolicyRepository):
    """Production RBAC repository backed by the normalized PostgreSQL schema.

    Public API contracts keep stable tenant/user/role codes. PostgreSQL UUIDs
    remain internal foreign keys and are resolved at this boundary.
    """

    def __init__(self, pool: PostgreSQLConnectionPool, *, owns_pool: bool = False) -> None:
        self.pool = pool
        self.owns_pool = owns_pool

    def close(self) -> None:
        if self.owns_pool:
            self.pool.close()

    def list_roles(self, tenant_id: str | None = None) -> list[Role]:
        params: tuple[Any, ...] = ()
        where = "WHERE r.status = 'active'"
        if tenant_id is not None:
            where += " AND (t.tenant_code = %s OR r.tenant_id IS NULL)"
            params = (tenant_id,)
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT r.role_code, t.tenant_code, r.role_name, r.role_level,
                       r.is_system, creator.external_subject AS created_by
                FROM auth_roles r
                LEFT JOIN platform_tenants t ON t.tenant_id = r.tenant_id
                LEFT JOIN platform_user_profiles creator ON creator.user_id = r.created_by
                {where}
                ORDER BY COALESCE(t.tenant_code, ''), r.role_level DESC, r.role_name
                """,
                params,
            )
            rows = cursor.fetchall()
        return [self._role_from_row(row) for row in rows]

    def get_role(self, role_id: str) -> Role | None:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT r.role_code, t.tenant_code, r.role_name, r.role_level,
                       r.is_system, creator.external_subject AS created_by
                FROM auth_roles r
                LEFT JOIN platform_tenants t ON t.tenant_id = r.tenant_id
                LEFT JOIN platform_user_profiles creator ON creator.user_id = r.created_by
                WHERE r.role_code = %s AND r.status = 'active'
                ORDER BY r.tenant_id NULLS LAST
                LIMIT 1
                """,
                (role_id,),
            )
            row = cursor.fetchone()
        return self._role_from_row(row) if row else None

    def upsert_role(self, role: Role) -> Role:
        with self._transaction() as connection:
            self._upsert_role(connection, role)
        return role

    def list_user_assignments(self, user_id: str | None = None) -> list[RoleAssignment]:
        params: tuple[Any, ...] = ()
        where = "WHERE (a.expires_at IS NULL OR a.expires_at > now())"
        if user_id is not None:
            where += " AND u.external_subject = %s"
            params = (user_id,)
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT u.external_subject AS user_code, t.tenant_code, r.role_code,
                       grantor.external_subject AS granted_by
                FROM auth_role_assignments a
                JOIN platform_user_profiles u ON u.user_id = a.user_id
                LEFT JOIN platform_tenants t ON t.tenant_id = a.tenant_id
                JOIN auth_roles r ON r.role_id = a.role_id
                LEFT JOIN platform_user_profiles grantor ON grantor.user_id = a.granted_by
                {where}
                ORDER BY u.external_subject, t.tenant_code, r.role_code
                """,
                params,
            )
            rows = cursor.fetchall()
        return [self._assignment_from_row(row) for row in rows]

    def get_user_roles(self, user_id: str, tenant_id: str) -> list[RoleAssignment]:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT u.external_subject AS user_code, t.tenant_code, r.role_code,
                       grantor.external_subject AS granted_by
                FROM auth_role_assignments a
                JOIN platform_user_profiles u ON u.user_id = a.user_id
                LEFT JOIN platform_tenants t ON t.tenant_id = a.tenant_id
                JOIN auth_roles r ON r.role_id = a.role_id
                LEFT JOIN platform_user_profiles grantor ON grantor.user_id = a.granted_by
                WHERE u.external_subject = %s AND (t.tenant_code = %s OR a.tenant_id IS NULL)
                  AND r.status = 'active' AND u.status = 'active'
                  AND (a.expires_at IS NULL OR a.expires_at > now())
                ORDER BY r.role_code
                """,
                (user_id, tenant_id),
            )
            rows = cursor.fetchall()
        return [self._assignment_from_row(row) for row in rows]

    def replace_user_assignments(self, user_id: str, assignments: list[RoleAssignment]) -> None:
        if any(item.user_id != user_id for item in assignments):
            raise ValueError("assignment_user_mismatch")
        with self._transaction() as connection:
            internal_user_id = PostgreSQLIdentityResolver.user_id(connection, user_id)
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM auth_role_assignments WHERE user_id = %s", (internal_user_id,))
                cursor.execute(
                    """
                    UPDATE platform_user_tenant_memberships
                    SET membership_status = 'left'
                    WHERE user_id = %s AND membership_status <> 'left'
                    """,
                    (internal_user_id,),
                )
            for assignment in assignments:
                self._insert_assignment(connection, assignment)

    def delete_user_assignments(self, user_id: str) -> None:
        with self._transaction() as connection:
            internal_user_id = PostgreSQLIdentityResolver.user_id(connection, user_id, required=False)
            if internal_user_id is None:
                return
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM auth_role_assignments WHERE user_id = %s", (internal_user_id,))
                cursor.execute(
                    """
                    UPDATE platform_user_tenant_memberships
                    SET membership_status = 'left'
                    WHERE user_id = %s AND membership_status <> 'left'
                    """,
                    (internal_user_id,),
                )

    def get_role_policies(self, role_id: str) -> list[PermissionPolicy]:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT r.role_code, t.tenant_code, p.resource_pattern, p.action, p.effect,
                       p.org_scope, p.row_filter, p.field_scope, p.metric_scope, p.priority
                FROM auth_permission_policies p
                JOIN auth_roles r ON r.role_id = p.role_id
                LEFT JOIN platform_tenants t ON t.tenant_id = p.tenant_id
                WHERE r.role_code = %s
                ORDER BY p.priority ASC, p.created_at ASC, p.policy_id ASC
                """,
                (role_id,),
            )
            rows = cursor.fetchall()
        return [self._policy_from_row(row) for row in rows]

    def get_manageable_role_ids(self, role_id: str) -> set[str]:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT target.role_code
                FROM auth_manageable_roles m
                JOIN auth_roles source ON source.role_id = m.role_id
                JOIN auth_roles target ON target.role_id = m.manageable_role_id
                WHERE source.role_code = %s AND target.status = 'active'
                """,
                (role_id,),
            )
            rows = cursor.fetchall()
        return {str(_value(row, "role_code", 0)) for row in rows}

    def replace_role_policies(self, role_id: str, policies: list[PermissionPolicy]) -> None:
        if any(policy.role_id != role_id for policy in policies):
            raise ValueError("policy_role_mismatch")
        with self._transaction() as connection:
            internal_role_id = PostgreSQLIdentityResolver.role_id(connection, role_id)
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM auth_permission_policies WHERE role_id = %s", (internal_role_id,))
            for policy in policies:
                self._insert_policy(connection, policy)

    def replace_manageable_role_ids(self, role_id: str, manageable_role_ids: set[str]) -> None:
        if role_id in manageable_role_ids:
            raise ValueError("role_cannot_manage_itself")
        with self._transaction() as connection:
            internal_role_id = PostgreSQLIdentityResolver.role_id(connection, role_id)
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM auth_manageable_roles WHERE role_id = %s", (internal_role_id,))
                for manageable_role_id in sorted(manageable_role_ids):
                    target_id = PostgreSQLIdentityResolver.role_id(connection, manageable_role_id)
                    cursor.execute(
                        """
                        INSERT INTO auth_manageable_roles(role_id, manageable_role_id)
                        VALUES (%s, %s) ON CONFLICT DO NOTHING
                        """,
                        (internal_role_id, target_id),
                    )

    def seed(
        self,
        roles: Iterable[Role],
        assignments: Iterable[RoleAssignment],
        policies: Iterable[PermissionPolicy],
        manageable_roles: dict[str, set[str]] | None = None,
    ) -> None:
        """Explicit, idempotent provisioning; never called implicitly at startup."""

        role_items = list(roles)
        assignment_items = list(assignments)
        policy_items = list(policies)
        policies_by_role: dict[str, list[PermissionPolicy]] = {}
        for policy in policy_items:
            policies_by_role.setdefault(policy.role_id, []).append(policy)
        with self._transaction() as connection:
            for role in role_items:
                self._upsert_role(connection, role)
            for assignment in assignment_items:
                self._insert_assignment(connection, assignment)
            for role_id, role_policies in policies_by_role.items():
                internal_role_id = PostgreSQLIdentityResolver.role_id(connection, role_id)
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM auth_permission_policies WHERE role_id = %s", (internal_role_id,))
                for policy in role_policies:
                    self._insert_policy(connection, policy)
            for source_role, targets in (manageable_roles or {}).items():
                source_id = PostgreSQLIdentityResolver.role_id(connection, source_role)
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM auth_manageable_roles WHERE role_id = %s", (source_id,))
                    for target in sorted(targets):
                        target_id = PostgreSQLIdentityResolver.role_id(connection, target)
                        cursor.execute(
                            """
                            INSERT INTO auth_manageable_roles(role_id, manageable_role_id)
                            VALUES (%s, %s) ON CONFLICT DO NOTHING
                            """,
                            (source_id, target_id),
                        )

    def _upsert_role(self, connection: Any, role: Role) -> None:
        tenant_key = None
        if role.tenant_id not in (None, "*"):
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, str(role.tenant_id))
        creator_key = None
        if role.created_by:
            creator_key = PostgreSQLIdentityResolver.user_id(connection, role.created_by, required=False)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO auth_roles(
                    tenant_id, role_code, role_name, role_level, is_system, status, created_by
                ) VALUES (%s, %s, %s, %s, %s, 'active', %s)
                ON CONFLICT (COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid), role_code)
                DO UPDATE SET role_name = EXCLUDED.role_name, role_level = EXCLUDED.role_level,
                              is_system = EXCLUDED.is_system, status = 'active',
                              created_by = EXCLUDED.created_by, updated_at = now()
                """,
                (tenant_key, role.role_id, role.name, int(role.level), role.is_system, creator_key),
            )

    def _insert_assignment(self, connection: Any, assignment: RoleAssignment) -> None:
        user_key = PostgreSQLIdentityResolver.user_id(connection, assignment.user_id)
        tenant_key = None
        if assignment.tenant_id != "*":
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, assignment.tenant_id)
        role_key = PostgreSQLIdentityResolver.role_id(
            connection,
            assignment.role_id,
            None if assignment.tenant_id == "*" else assignment.tenant_id,
        )
        if assignment.tenant_id == "*":
            with connection.cursor() as cursor:
                cursor.execute("SELECT tenant_id IS NULL AS is_global FROM auth_roles WHERE role_id = %s", (role_key,))
                row = cursor.fetchone()
            if not row or not bool(_value(row, "is_global", 0)):
                raise ValueError("global_assignment_requires_global_role")
        grantor_key = (
            PostgreSQLIdentityResolver.user_id(connection, assignment.granted_by, required=False)
            if assignment.granted_by
            else None
        )
        with connection.cursor() as cursor:
            if tenant_key is not None:
                cursor.execute(
                    """
                    INSERT INTO platform_user_tenant_memberships(
                        tenant_id, user_id, membership_status, joined_at
                    ) VALUES (%s, %s, 'active', now())
                    ON CONFLICT (tenant_id, user_id) DO UPDATE SET
                        membership_status = 'active',
                        joined_at = COALESCE(platform_user_tenant_memberships.joined_at, now())
                    """,
                    (tenant_key, user_key),
                )
            cursor.execute(
                """
                INSERT INTO auth_role_assignments(tenant_id, user_id, role_id, granted_by)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid), user_id, role_id)
                DO UPDATE SET granted_by = EXCLUDED.granted_by, granted_at = now(), expires_at = NULL
                """,
                (tenant_key, user_key, role_key, grantor_key),
            )

    def _insert_policy(self, connection: Any, policy: PermissionPolicy) -> None:
        role_key = PostgreSQLIdentityResolver.role_id(connection, policy.role_id, policy.tenant_id)
        tenant_key = None
        if policy.tenant_id not in (None, "*"):
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, str(policy.tenant_id))
        attrs = dict(policy.attrs)
        org_scope = attrs.pop("org_scope", [])
        row_filter = dict(attrs.pop("row_filter", {}))
        field_scope = attrs.pop("fields", [])
        metric_scope = attrs.pop("metric_ids", [])
        if _EXTRA_POLICY_ATTRS in row_filter:
            raise ValueError("reserved_policy_attribute")
        if attrs:
            row_filter[_EXTRA_POLICY_ATTRS] = attrs
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO auth_permission_policies(
                    role_id, tenant_id, resource_pattern, action, effect,
                    org_scope, row_filter, field_scope, metric_scope, priority
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s)
                """,
                (
                    role_key,
                    tenant_key,
                    policy.obj,
                    policy.act,
                    policy.effect,
                    _json(org_scope),
                    _json(row_filter),
                    _json(field_scope),
                    _json(metric_scope),
                    policy.priority,
                ),
            )

    @staticmethod
    def _role_from_row(row: Any) -> Role:
        return Role(
            role_id=str(_value(row, "role_code", 0)),
            tenant_id=_optional_str(_value(row, "tenant_code", 1)),
            name=str(_value(row, "role_name", 2)),
            level=RoleLevel(int(_value(row, "role_level", 3))),
            is_system=bool(_value(row, "is_system", 4)),
            created_by=_optional_str(_value(row, "created_by", 5)),
        )

    @staticmethod
    def _assignment_from_row(row: Any) -> RoleAssignment:
        return RoleAssignment(
            user_id=str(_value(row, "user_code", 0)),
            tenant_id=_optional_str(_value(row, "tenant_code", 1)) or "*",
            role_id=str(_value(row, "role_code", 2)),
            granted_by=_optional_str(_value(row, "granted_by", 3)),
        )

    @staticmethod
    def _policy_from_row(row: Any) -> PermissionPolicy:
        org_scope = _json_value(_value(row, "org_scope", 5), [])
        row_filter = dict(_json_value(_value(row, "row_filter", 6), {}))
        extra = row_filter.pop(_EXTRA_POLICY_ATTRS, {})
        attrs = dict(extra) if isinstance(extra, dict) else {}
        field_scope = _json_value(_value(row, "field_scope", 7), [])
        metric_scope = _json_value(_value(row, "metric_scope", 8), [])
        if org_scope:
            attrs["org_scope"] = org_scope
        if row_filter:
            attrs["row_filter"] = row_filter
        if field_scope:
            attrs["fields"] = field_scope
        if metric_scope:
            attrs["metric_ids"] = metric_scope
        return PermissionPolicy(
            role_id=str(_value(row, "role_code", 0)),
            tenant_id=_optional_str(_value(row, "tenant_code", 1)),
            obj=str(_value(row, "resource_pattern", 2)),
            act=str(_value(row, "action", 3)),
            effect=str(_value(row, "effect", 4)),  # type: ignore[arg-type]
            attrs=attrs,
            priority=int(_value(row, "priority", 9)),
        )

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        with self.pool.connection() as connection:
            yield connection

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self.pool.connection() as connection:
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]
