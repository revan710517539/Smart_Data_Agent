from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from backend.platform.storage import connect_sqlite
from typing import Iterable

from .models import PermissionPolicy, Role, RoleAssignment, RoleLevel
from .rbac import RBACSeed
from .repository import PolicyRepository


class SQLitePolicyRepository(PolicyRepository):
    """SQLite-backed policy repository for local and single-node deployments.

    The enforcer keeps the Casbin-like model in code while this repository keeps
    policy data outside the model. It gives the project a durable boundary before
    moving the same tables to PostgreSQL.
    """

    def __init__(self, db_path: str | Path, initialize: bool = True) -> None:
        self.db_path = str(db_path)
        self._conn = connect_sqlite(self.db_path)
        self._conn.row_factory = sqlite3.Row
        if initialize:
            self.init_schema()

    def close(self) -> None:
        self._conn.close()

    def init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS auth_roles (
                role_id TEXT PRIMARY KEY,
                tenant_id TEXT,
                name TEXT NOT NULL,
                level INTEGER NOT NULL,
                is_system INTEGER NOT NULL DEFAULT 0,
                created_by TEXT
            );

            CREATE TABLE IF NOT EXISTS auth_role_assignments (
                user_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                role_id TEXT NOT NULL REFERENCES auth_roles(role_id) ON DELETE CASCADE,
                granted_by TEXT,
                PRIMARY KEY (user_id, tenant_id, role_id)
            );

            CREATE TABLE IF NOT EXISTS auth_permission_policies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role_id TEXT NOT NULL REFERENCES auth_roles(role_id) ON DELETE CASCADE,
                tenant_id TEXT,
                obj TEXT NOT NULL,
                act TEXT NOT NULL,
                effect TEXT NOT NULL DEFAULT 'allow',
                attrs TEXT NOT NULL DEFAULT '{}',
                priority INTEGER NOT NULL DEFAULT 100
            );

            CREATE TABLE IF NOT EXISTS auth_manageable_roles (
                role_id TEXT NOT NULL REFERENCES auth_roles(role_id) ON DELETE CASCADE,
                manageable_role_id TEXT NOT NULL REFERENCES auth_roles(role_id) ON DELETE CASCADE,
                PRIMARY KEY (role_id, manageable_role_id),
                CHECK (role_id <> manageable_role_id)
            );

            CREATE INDEX IF NOT EXISTS idx_auth_role_assignments_user_tenant
                ON auth_role_assignments(user_id, tenant_id);
            CREATE INDEX IF NOT EXISTS idx_auth_permission_policies_role
                ON auth_permission_policies(role_id, priority);

            DELETE FROM auth_permission_policies
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM auth_permission_policies
                GROUP BY role_id, COALESCE(tenant_id, '*'), obj, act, effect, attrs, priority
            );

            CREATE UNIQUE INDEX IF NOT EXISTS uq_auth_permission_policy_identity
                ON auth_permission_policies(
                    role_id,
                    COALESCE(tenant_id, '*'),
                    obj,
                    act,
                    effect,
                    attrs,
                    priority
                );
            """
        )
        self._conn.commit()

    def clear(self) -> None:
        self._conn.executescript(
            """
            DELETE FROM auth_manageable_roles;
            DELETE FROM auth_permission_policies;
            DELETE FROM auth_role_assignments;
            DELETE FROM auth_roles;
            """
        )
        self._conn.commit()

    def seed(
        self,
        roles: Iterable[Role],
        assignments: Iterable[RoleAssignment],
        policies: Iterable[PermissionPolicy],
        manageable_roles: dict[str, set[str]] | None = None,
    ) -> None:
        with self._conn:
            self._conn.executemany(
                """
                INSERT OR REPLACE INTO auth_roles(role_id, tenant_id, name, level, is_system, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        role.role_id,
                        role.tenant_id,
                        role.name,
                        int(role.level),
                        1 if role.is_system else 0,
                        role.created_by,
                    )
                    for role in roles
                ],
            )
            self._conn.executemany(
                """
                INSERT OR IGNORE INTO auth_role_assignments(user_id, tenant_id, role_id, granted_by)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (assignment.user_id, assignment.tenant_id, assignment.role_id, assignment.granted_by)
                    for assignment in assignments
                ],
            )
            self._conn.executemany(
                """
                INSERT OR IGNORE INTO auth_permission_policies(role_id, tenant_id, obj, act, effect, attrs, priority)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        policy.role_id,
                        policy.tenant_id,
                        policy.obj,
                        policy.act,
                        policy.effect,
                        json.dumps(policy.attrs, ensure_ascii=False, sort_keys=True),
                        policy.priority,
                    )
                    for policy in policies
                ],
            )
            if manageable_roles:
                self._conn.executemany(
                    """
                    INSERT OR IGNORE INTO auth_manageable_roles(role_id, manageable_role_id)
                    VALUES (?, ?)
                    """,
                    [
                        (role_id, manageable_role_id)
                        for role_id, role_ids in manageable_roles.items()
                        for manageable_role_id in role_ids
                    ],
                )

    def seed_rbac(self, seed: RBACSeed, reset: bool = False) -> None:
        if reset:
            self.clear()
        self.seed(seed.roles, seed.assignments, seed.policies, seed.manageable_roles)

    def list_roles(self, tenant_id: str | None = None) -> list[Role]:
        if tenant_id is None:
            rows = self._conn.execute(
                """
                SELECT role_id, tenant_id, name, level, is_system, created_by
                FROM auth_roles
                ORDER BY COALESCE(tenant_id, ''), level DESC, name
                """
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT role_id, tenant_id, name, level, is_system, created_by
                FROM auth_roles
                WHERE tenant_id = ? OR tenant_id IS NULL OR tenant_id = '*'
                ORDER BY COALESCE(tenant_id, ''), level DESC, name
                """,
                (tenant_id,),
            ).fetchall()
        return [self._role_from_row(row) for row in rows]

    def get_role(self, role_id: str) -> Role | None:
        row = self._conn.execute(
            """
            SELECT role_id, tenant_id, name, level, is_system, created_by
            FROM auth_roles
            WHERE role_id = ?
            """,
            (role_id,),
        ).fetchone()
        if row is None:
            return None
        return self._role_from_row(row)

    def upsert_role(self, role: Role) -> Role:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO auth_roles(role_id, tenant_id, name, level, is_system, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(role_id) DO UPDATE SET
                    tenant_id = excluded.tenant_id,
                    name = excluded.name,
                    level = excluded.level,
                    is_system = excluded.is_system,
                    created_by = excluded.created_by
                """,
                (
                    role.role_id,
                    role.tenant_id,
                    role.name,
                    int(role.level),
                    1 if role.is_system else 0,
                    role.created_by,
                ),
            )
        return role

    def list_user_assignments(self, user_id: str | None = None) -> list[RoleAssignment]:
        if user_id is None:
            rows = self._conn.execute(
                """
                SELECT user_id, tenant_id, role_id, granted_by
                FROM auth_role_assignments
                ORDER BY user_id, tenant_id, role_id
                """
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT user_id, tenant_id, role_id, granted_by
                FROM auth_role_assignments
                WHERE user_id = ?
                ORDER BY user_id, tenant_id, role_id
                """,
                (user_id,),
            ).fetchall()
        return [self._assignment_from_row(row) for row in rows]

    def replace_user_assignments(self, user_id: str, assignments: list[RoleAssignment]) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM auth_role_assignments WHERE user_id = ?", (user_id,))
            self._conn.executemany(
                """
                INSERT OR IGNORE INTO auth_role_assignments(user_id, tenant_id, role_id, granted_by)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (assignment.user_id, assignment.tenant_id, assignment.role_id, assignment.granted_by)
                    for assignment in assignments
                ],
            )

    def delete_user_assignments(self, user_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM auth_role_assignments WHERE user_id = ?", (user_id,))

    @staticmethod
    def _role_from_row(row: sqlite3.Row) -> Role:
        return Role(
            role_id=row["role_id"],
            tenant_id=row["tenant_id"],
            name=row["name"],
            level=RoleLevel(row["level"]),
            is_system=bool(row["is_system"]),
            created_by=row["created_by"],
        )

    @staticmethod
    def _assignment_from_row(row: sqlite3.Row) -> RoleAssignment:
        return RoleAssignment(
            user_id=row["user_id"],
            tenant_id=row["tenant_id"],
            role_id=row["role_id"],
            granted_by=row["granted_by"],
        )

    def get_user_roles(self, user_id: str, tenant_id: str) -> list[RoleAssignment]:
        rows = self._conn.execute(
            """
            SELECT user_id, tenant_id, role_id, granted_by
            FROM auth_role_assignments
            WHERE user_id = ? AND tenant_id IN (?, '*')
            ORDER BY tenant_id, role_id
            """,
            (user_id, tenant_id),
        ).fetchall()
        return [self._assignment_from_row(row) for row in rows]

    def get_role_policies(self, role_id: str) -> list[PermissionPolicy]:
        rows = self._conn.execute(
            """
            SELECT role_id, tenant_id, obj, act, effect, attrs, priority
            FROM auth_permission_policies
            WHERE role_id = ?
            ORDER BY priority ASC, id ASC
            """,
            (role_id,),
        ).fetchall()
        return [
            PermissionPolicy(
                role_id=row["role_id"],
                tenant_id=row["tenant_id"],
                obj=row["obj"],
                act=row["act"],
                effect=row["effect"],
                attrs=json.loads(row["attrs"] or "{}"),
                priority=row["priority"],
            )
            for row in rows
        ]

    def get_manageable_role_ids(self, role_id: str) -> set[str]:
        rows = self._conn.execute(
            """
            SELECT manageable_role_id
            FROM auth_manageable_roles
            WHERE role_id = ?
            """,
            (role_id,),
        ).fetchall()
        return {row["manageable_role_id"] for row in rows}

    def replace_role_policies(self, role_id: str, policies: list[PermissionPolicy]) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM auth_permission_policies WHERE role_id = ?", (role_id,))
            self._conn.executemany(
                """
                INSERT INTO auth_permission_policies(role_id, tenant_id, obj, act, effect, attrs, priority)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        policy.role_id,
                        policy.tenant_id,
                        policy.obj,
                        policy.act,
                        policy.effect,
                        json.dumps(policy.attrs, ensure_ascii=False, sort_keys=True),
                        policy.priority,
                    )
                    for policy in policies
                ],
            )

    def replace_manageable_role_ids(self, role_id: str, manageable_role_ids: set[str]) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM auth_manageable_roles WHERE role_id = ?", (role_id,))
            self._conn.executemany(
                """
                INSERT OR IGNORE INTO auth_manageable_roles(role_id, manageable_role_id)
                VALUES (?, ?)
                """,
                [(role_id, manageable_role_id) for manageable_role_id in sorted(manageable_role_ids)],
            )
