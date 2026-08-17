from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .models import PermissionPolicy, Role, RoleAssignment, RoleLevel
from .seed import CUSTOM_ROLE_CANDIDATES, DEFAULT_ROLE_NAMES, MANDATORY_MENU_KEYS, OPERATING_TENANTS


SUPER_ADMIN_ROLE_ID = "role:global:super_admin"
SUPER_ADMIN_USER_ID = "u_super_admin"
DEFAULT_OPERATOR_MENU_KEYS = (
    "data-assets",
    "data-assets.metrics",
    "self-analysis",
    "self-analysis.visual-reports",
    "self-analysis.smart-analysis",
    "self-analysis.analysis-config",
    "data-assets.data-management",
)
DEFAULT_TENANT_ADMIN_MENU_KEYS = (
    "dashboard",
    "business-analysis",
    "business-analysis.weekly-report",
    "business-analysis.sandbox",
    "business-analysis.funnel",
    "business-analysis.supervision",
    "business-analysis.email-daily",
    "market-customer",
    "market-customer.segment",
    "market-customer.competition",
    "self-analysis",
    "self-analysis.visual-reports",
    "self-analysis.smart-analysis",
    "self-analysis.my-reports",
    "self-analysis.analysis-config",
    "task-workbench",
    "task-workbench.todos",
    "task-workbench.tasks",
    "task-workbench.skills",
    "data-assets",
    "data-assets.metrics",
    "data-assets.knowledge",
    "data-assets.data-management",
    "data-assets.quality",
    "data-assets.tools",
    "notifications",
    "notifications.alerts",
    "notifications.subscriptions",
    "notifications.history",
    "settings",
    "settings.users",
    "settings.roles",
)


@dataclass(frozen=True)
class TenantRoleBundle:
    tenant_id: str
    admin_role_id: str
    operator_role_id: str
    custom_role_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RBACSeed:
    roles: tuple[Role, ...]
    assignments: tuple[RoleAssignment, ...]
    policies: tuple[PermissionPolicy, ...]
    manageable_roles: dict[str, set[str]] = field(default_factory=dict)
    tenant_roles: tuple[TenantRoleBundle, ...] = ()


def normalize_tenant_id(tenant_name: str) -> str:
    return f"tenant:{tenant_name}"


def tenant_role_id(tenant_id: str, role_name: str) -> str:
    return f"role:{tenant_id}:{role_name}"


def build_default_rbac_seed(
    tenant_names: Iterable[str] = OPERATING_TENANTS,
    custom_role_names: Iterable[str] = CUSTOM_ROLE_CANDIDATES,
) -> RBACSeed:
    """Build default RBAC policies with a single global super administrator.

    The global super administrator is not duplicated under tenants. Each tenant receives
    only administrator, operator, and optional custom roles.
    """

    tenants = tuple(normalize_tenant_id(name) for name in tenant_names)
    custom_roles = tuple(custom_role_names)
    roles: list[Role] = [
        Role(SUPER_ADMIN_ROLE_ID, None, "超级管理员", RoleLevel.SUPER_ADMIN, True),
    ]
    assignments: list[RoleAssignment] = [
        RoleAssignment(SUPER_ADMIN_USER_ID, "*", SUPER_ADMIN_ROLE_ID),
    ]
    policies: list[PermissionPolicy] = [
        PermissionPolicy(SUPER_ADMIN_ROLE_ID, "*", "*", "*", priority=0),
    ]
    manageable_roles: dict[str, set[str]] = {SUPER_ADMIN_ROLE_ID: set()}
    tenant_bundles: list[TenantRoleBundle] = []

    for tenant_id in tenants:
        admin_role_id = tenant_role_id(tenant_id, DEFAULT_ROLE_NAMES[0])
        operator_role_id = tenant_role_id(tenant_id, DEFAULT_ROLE_NAMES[1])
        custom_role_ids = tuple(tenant_role_id(tenant_id, role_name) for role_name in custom_roles)

        roles.extend(
            [
                Role(admin_role_id, tenant_id, "管理员", RoleLevel.TENANT_ADMIN, True, created_by=SUPER_ADMIN_USER_ID),
                Role(operator_role_id, tenant_id, "操作员", RoleLevel.OPERATOR, True, created_by=SUPER_ADMIN_USER_ID),
                *[
                    Role(role_id, tenant_id, role_name, RoleLevel.OPERATOR, False, created_by=admin_role_id)
                    for role_id, role_name in zip(custom_role_ids, custom_roles)
                ],
            ]
        )
        manageable_roles[SUPER_ADMIN_ROLE_ID].update({admin_role_id, operator_role_id, *custom_role_ids})
        manageable_roles[admin_role_id] = {operator_role_id, *custom_role_ids}

        policies.extend(
            [
                PermissionPolicy(admin_role_id, tenant_id, "button:*", "*"),
                PermissionPolicy(admin_role_id, tenant_id, "role:*", "manage", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "approval:*", "manage", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "metric:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "metric:*", "create", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "asset:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "asset:*", "create", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "asset:*", "manage", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "knowledge:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "knowledge:*", "create", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "knowledge:*", "manage", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "memory:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "memory:*", "create", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "memory:*", "manage", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "automation:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "automation:*", "create", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "automation:*", "manage", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "notification:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "notification:*", "create", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "market:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "market:*", "create", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "market:*", "manage", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "application:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "application:*", "execute", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "report:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "report:*", "create", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "report:*", "manage", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "message_board:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "message_board:*", "create", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "message_board:*", "manage", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(admin_role_id, tenant_id, "skill:supersonic.query", "execute"),
                PermissionPolicy(admin_role_id, tenant_id, "skill:data.analysis.profile", "execute"),
                PermissionPolicy(admin_role_id, tenant_id, "skill:data.governance.assess", "execute"),
                PermissionPolicy(admin_role_id, tenant_id, "skill:conclusion.generate", "execute"),
                PermissionPolicy(admin_role_id, tenant_id, "skill:bi.report.generate", "execute"),
                PermissionPolicy(admin_role_id, tenant_id, "mcp:database.query", "execute"),
                PermissionPolicy(admin_role_id, tenant_id, "mcp:database.schema", "execute"),
                PermissionPolicy(admin_role_id, tenant_id, "mcp:knowledge.search", "execute"),
                PermissionPolicy(admin_role_id, tenant_id, "mcp:knowledge.ingest", "execute"),
                PermissionPolicy(operator_role_id, tenant_id, "metric:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "metric:*", "create", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "asset:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "asset:*", "create", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "knowledge:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "knowledge:*", "create", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "memory:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "memory:*", "create", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "automation:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "automation:*", "create", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "notification:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "notification:*", "create", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "market:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "market:*", "create", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "application:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "application:*", "execute", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "report:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "message_board:*", "read", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "message_board:*", "create", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "message_board:*", "manage", attrs={"tenant_id": tenant_id}),
                PermissionPolicy(operator_role_id, tenant_id, "skill:supersonic.query", "execute"),
                PermissionPolicy(operator_role_id, tenant_id, "skill:data.analysis.profile", "execute"),
                PermissionPolicy(operator_role_id, tenant_id, "skill:data.governance.assess", "execute"),
                PermissionPolicy(operator_role_id, tenant_id, "skill:conclusion.generate", "execute"),
                PermissionPolicy(operator_role_id, tenant_id, "skill:bi.report.generate", "execute"),
                PermissionPolicy(operator_role_id, tenant_id, "mcp:database.query", "execute"),
                PermissionPolicy(operator_role_id, tenant_id, "mcp:database.schema", "execute"),
                PermissionPolicy(operator_role_id, tenant_id, "mcp:knowledge.search", "execute"),
                PermissionPolicy(operator_role_id, tenant_id, "role:*", "manage", effect="deny", priority=10),
            ]
        )
        for menu_key in DEFAULT_TENANT_ADMIN_MENU_KEYS:
            policies.append(PermissionPolicy(admin_role_id, tenant_id, f"menu:{menu_key}", "read"))
        for mandatory_key in MANDATORY_MENU_KEYS:
            policies.append(PermissionPolicy(admin_role_id, tenant_id, f"menu:{mandatory_key}", "read", priority=5))
        for menu_key in DEFAULT_OPERATOR_MENU_KEYS:
            policies.append(PermissionPolicy(operator_role_id, tenant_id, f"menu:{menu_key}", "read"))
        for mandatory_key in MANDATORY_MENU_KEYS:
            policies.append(PermissionPolicy(operator_role_id, tenant_id, f"menu:{mandatory_key}", "read", priority=5))
            for custom_role_id in custom_role_ids:
                policies.append(PermissionPolicy(custom_role_id, tenant_id, f"menu:{mandatory_key}", "read", priority=5))
        for custom_role_id in custom_role_ids:
            for menu_key in DEFAULT_OPERATOR_MENU_KEYS:
                policies.append(PermissionPolicy(custom_role_id, tenant_id, f"menu:{menu_key}", "read"))
            policies.extend(
                [
                    PermissionPolicy(custom_role_id, tenant_id, "metric:*", "read", attrs={"tenant_id": tenant_id}),
                    PermissionPolicy(custom_role_id, tenant_id, "asset:*", "read", attrs={"tenant_id": tenant_id}),
                    PermissionPolicy(custom_role_id, tenant_id, "knowledge:*", "read", attrs={"tenant_id": tenant_id}),
                    PermissionPolicy(custom_role_id, tenant_id, "memory:*", "read", attrs={"tenant_id": tenant_id}),
                    PermissionPolicy(custom_role_id, tenant_id, "automation:*", "read", attrs={"tenant_id": tenant_id}),
                    PermissionPolicy(custom_role_id, tenant_id, "notification:*", "read", attrs={"tenant_id": tenant_id}),
                    PermissionPolicy(custom_role_id, tenant_id, "market:*", "read", attrs={"tenant_id": tenant_id}),
                    PermissionPolicy(custom_role_id, tenant_id, "application:*", "read", attrs={"tenant_id": tenant_id}),
                    PermissionPolicy(custom_role_id, tenant_id, "application:*", "execute", attrs={"tenant_id": tenant_id}),
                    PermissionPolicy(custom_role_id, tenant_id, "report:*", "read", attrs={"tenant_id": tenant_id}),
                    PermissionPolicy(custom_role_id, tenant_id, "message_board:*", "read", attrs={"tenant_id": tenant_id}),
                    PermissionPolicy(custom_role_id, tenant_id, "message_board:*", "create", attrs={"tenant_id": tenant_id}),
                    PermissionPolicy(custom_role_id, tenant_id, "message_board:*", "manage", attrs={"tenant_id": tenant_id}),
                    PermissionPolicy(custom_role_id, tenant_id, "skill:supersonic.query", "execute"),
                    PermissionPolicy(custom_role_id, tenant_id, "skill:data.analysis.profile", "execute"),
                    PermissionPolicy(custom_role_id, tenant_id, "skill:data.governance.assess", "execute"),
                    PermissionPolicy(custom_role_id, tenant_id, "skill:conclusion.generate", "execute"),
                    PermissionPolicy(custom_role_id, tenant_id, "skill:bi.report.generate", "execute"),
                    PermissionPolicy(custom_role_id, tenant_id, "mcp:database.query", "execute"),
                    PermissionPolicy(custom_role_id, tenant_id, "mcp:database.schema", "execute"),
                    PermissionPolicy(custom_role_id, tenant_id, "mcp:knowledge.search", "execute"),
                ]
            )

        tenant_bundles.append(
            TenantRoleBundle(
                tenant_id=tenant_id,
                admin_role_id=admin_role_id,
                operator_role_id=operator_role_id,
                custom_role_ids=custom_role_ids,
            )
        )

    return RBACSeed(
        roles=tuple(roles),
        assignments=tuple(assignments),
        policies=tuple(policies),
        manageable_roles=manageable_roles,
        tenant_roles=tuple(tenant_bundles),
    )


def assert_single_global_super_admin(roles: Iterable[Role]) -> None:
    super_roles = [role for role in roles if role.level == RoleLevel.SUPER_ADMIN]
    if len(super_roles) != 1:
        raise ValueError("Exactly one global super administrator role is required.")
    if not super_roles[0].is_global:
        raise ValueError("The super administrator role must be global, not tenant-scoped.")
