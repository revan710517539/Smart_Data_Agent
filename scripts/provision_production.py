#!/usr/bin/env python3
"""Explicitly provision a production tenant, identities, org root and RBAC.

This command is intentionally separate from application startup. It is safe to
re-run with the same inputs and never creates demo data, model credentials or
data-source credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.authz import PostgreSQLPolicyRepository, SUPER_ADMIN_USER_ID, build_default_rbac_seed
from backend.authz.models import RoleAssignment
from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database import MySQLConnectionPool, MySQLStoreConnectionPool, apply_mysql_schema


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision Smart Data Agent production identity and RBAC roots.")
    parser.add_argument("--database-url", default=os.getenv("SMART_DATA_AGENT_DATABASE_URL", ""))
    parser.add_argument("--tenant-slug", required=True, help="Stable slug; tenant code becomes tenant:<slug>.")
    parser.add_argument("--tenant-name", required=True, help="Display name shown to users.")
    parser.add_argument("--super-admin-subject", required=True, help="Enterprise IdP subject for the one global super administrator.")
    parser.add_argument("--super-admin-email", required=True)
    parser.add_argument("--super-admin-name", required=True)
    parser.add_argument("--users-file", help="Optional JSON array of tenant users with subject/email/name/role/department.")
    parser.add_argument("--custom-role", action="append", default=[], help="Optional custom role name; repeatable.")
    parser.add_argument("--skip-schema", action="store_true", help="Require schema to exist instead of applying it.")
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("--database-url or SMART_DATA_AGENT_DATABASE_URL is required")
    slug = str(args.tenant_slug).strip()
    if not slug or slug.startswith("tenant:") or len(slug) > 57:
        raise SystemExit("--tenant-slug must be a bare non-empty slug of at most 57 characters")
    tenant_code = f"tenant:{slug}"
    users = _load_users(args.users_file)
    _validate_users(users)

    raw_pool = MySQLConnectionPool(args.database_url, min_size=1, max_size=3)
    pool = MySQLStoreConnectionPool(raw_pool)
    try:
        if not args.skip_schema:
            with raw_pool.connection() as connection:
                apply_mysql_schema(args.database_url, connection=connection)
        with pool.connection() as connection:
            try:
                tenant_id = PostgreSQLIdentityResolver.ensure_tenant(connection, tenant_code, args.tenant_name)
                PostgreSQLIdentityResolver.ensure_tenant(connection, "__global__", "Global knowledge scope")
                super_user_id = PostgreSQLIdentityResolver.ensure_user(
                    connection,
                    args.super_admin_subject,
                    email=args.super_admin_email,
                    display_name=args.super_admin_name,
                )
                PostgreSQLIdentityResolver.ensure_user(
                    connection,
                    "system",
                    email="system@invalid.local",
                    display_name="Smart Data Agent System",
                )
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO platform_org_units(
                            tenant_id,org_code,org_name,org_type,path,status,created_by
                        ) VALUES (%s,'ROOT',%s,'tenant_root','/ROOT','active',%s)
                        ON CONFLICT (tenant_id,org_code) DO UPDATE SET
                            org_name=EXCLUDED.org_name,status='active',updated_at=now(),
                            lock_version=platform_org_units.lock_version+1
                        RETURNING org_unit_id
                        """,
                        (tenant_id, args.tenant_name, super_user_id),
                    )
                    root_org_id = _value(cursor.fetchone(), "org_unit_id", 0)
                    cursor.execute(
                        """
                        INSERT INTO platform_user_tenant_memberships(
                            tenant_id,user_id,org_unit_id,membership_status,joined_at
                        ) VALUES (%s,%s,%s,'active',now())
                        ON CONFLICT (tenant_id,user_id) DO UPDATE SET
                            org_unit_id=EXCLUDED.org_unit_id,membership_status='active',
                            joined_at=COALESCE(platform_user_tenant_memberships.joined_at,now())
                        """,
                        (tenant_id, super_user_id, root_org_id),
                    )
                department_ids: dict[str, Any] = {}
                for department in sorted({str(user.get("department") or "").strip() for user in users} - {""}):
                    org_code = "DEPT_" + hashlib.sha256(department.encode("utf-8")).hexdigest()[:12].upper()
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            INSERT INTO platform_org_units(
                                tenant_id,parent_org_unit_id,org_code,org_name,org_type,path,status,created_by
                            ) VALUES (%s,%s,%s,%s,'department',%s,'active',%s)
                            ON CONFLICT (tenant_id,org_code) DO UPDATE SET
                                org_name=EXCLUDED.org_name,parent_org_unit_id=EXCLUDED.parent_org_unit_id,
                                status='active',updated_at=now(),lock_version=platform_org_units.lock_version+1
                            RETURNING org_unit_id
                            """,
                            (tenant_id,root_org_id,org_code,department,f"/ROOT/{org_code}",super_user_id),
                        )
                        department_ids[department] = _value(cursor.fetchone(), "org_unit_id", 0)
                for user in users:
                    user_id = PostgreSQLIdentityResolver.ensure_user(
                        connection,
                        user["subject"],
                        email=user["email"],
                        display_name=user["name"],
                    )
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            INSERT INTO platform_user_tenant_memberships(
                                tenant_id,user_id,org_unit_id,membership_status,joined_at
                            ) VALUES (%s,%s,%s,'active',now())
                            ON CONFLICT (tenant_id,user_id) DO UPDATE SET
                                org_unit_id=EXCLUDED.org_unit_id,membership_status='active',
                                joined_at=COALESCE(platform_user_tenant_memberships.joined_at,now())
                            """,
                            (tenant_id,user_id,department_ids.get(str(user.get("department") or "").strip(),root_org_id)),
                        )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

        seed = build_default_rbac_seed([slug], args.custom_role)
        subject = str(args.super_admin_subject)
        roles = [
            replace(role, created_by=subject if role.created_by == SUPER_ADMIN_USER_ID else role.created_by)
            for role in seed.roles
        ]
        assignments = [
            replace(item, user_id=subject if item.user_id == SUPER_ADMIN_USER_ID else item.user_id, granted_by=subject)
            for item in seed.assignments
        ]
        bundle = seed.tenant_roles[0]
        role_by_name = {
            "admin": bundle.admin_role_id,
            "管理员": bundle.admin_role_id,
            "operator": bundle.operator_role_id,
            "操作员": bundle.operator_role_id,
        }
        for name, role_id in zip(args.custom_role, bundle.custom_role_ids):
            role_by_name[str(name)] = role_id
        for user in users:
            role_name = str(user.get("role") or "operator")
            role_id = role_by_name.get(role_name)
            if not role_id:
                raise SystemExit(f"Unknown role for {user['subject']}: {role_name}")
            assignments.append(RoleAssignment(user["subject"], tenant_code, role_id, granted_by=subject))
        PostgreSQLPolicyRepository(pool).seed(roles, assignments, seed.policies, seed.manageable_roles)

        with pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS count FROM auth_roles WHERE status='active'")
                role_count = int(_value(cursor.fetchone(), "count", 0))
                cursor.execute("SELECT COUNT(*) AS count FROM auth_permission_policies")
                policy_count = int(_value(cursor.fetchone(), "count", 0))
                cursor.execute("SELECT COUNT(*) AS count FROM platform_user_tenant_memberships WHERE tenant_id=%s AND membership_status='active'", (tenant_id,))
                member_count = int(_value(cursor.fetchone(), "count", 0))
        print(json.dumps({
            "status": "provisioned",
            "tenant_code": tenant_code,
            "tenant_name": args.tenant_name,
            "member_count": member_count,
            "role_count": role_count,
            "policy_count": policy_count,
            "super_admin_subject": subject,
        }, ensure_ascii=False, sort_keys=True))
    finally:
        pool.close()


def _load_users(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise SystemExit("--users-file must contain a JSON array")
    return [dict(item) for item in value if isinstance(item, dict)]


def _validate_users(users: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for index, user in enumerate(users):
        for field in ("subject", "email", "name"):
            if not str(user.get(field) or "").strip():
                raise SystemExit(f"users-file item {index} is missing {field}")
        subject = str(user["subject"])
        if subject in seen:
            raise SystemExit(f"duplicate users-file subject: {subject}")
        seen.add(subject)


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]


if __name__ == "__main__":
    main()
