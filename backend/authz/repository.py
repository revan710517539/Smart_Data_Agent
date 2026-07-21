from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Protocol

from .models import PermissionPolicy, Role, RoleAssignment


class PolicyRepository(Protocol):
    """Repository boundary so AuthEnforcer can load policies from SQL, cache, or tests."""

    def list_roles(self, tenant_id: str | None = None) -> list[Role]:
        ...

    def get_role(self, role_id: str) -> Role | None:
        ...

    def upsert_role(self, role: Role) -> Role:
        ...

    def list_user_assignments(self, user_id: str | None = None) -> list[RoleAssignment]:
        ...

    def get_user_roles(self, user_id: str, tenant_id: str) -> list[RoleAssignment]:
        ...

    def replace_user_assignments(self, user_id: str, assignments: list[RoleAssignment]) -> None:
        ...

    def delete_user_assignments(self, user_id: str) -> None:
        ...

    def get_role_policies(self, role_id: str) -> list[PermissionPolicy]:
        ...

    def get_manageable_role_ids(self, role_id: str) -> set[str]:
        ...

    def replace_role_policies(self, role_id: str, policies: list[PermissionPolicy]) -> None:
        ...

    def replace_manageable_role_ids(self, role_id: str, manageable_role_ids: set[str]) -> None:
        ...

    def seed(
        self,
        roles: Iterable[Role],
        assignments: Iterable[RoleAssignment],
        policies: Iterable[PermissionPolicy],
        manageable_roles: dict[str, set[str]] | None = None,
    ) -> None:
        ...


class InMemoryPolicyRepository:
    """Small adapter for tests and local prototypes. Production should back this with DB queries."""

    def __init__(
        self,
        roles: list[Role],
        assignments: list[RoleAssignment],
        policies: list[PermissionPolicy],
        manageable_roles: dict[str, set[str]] | None = None,
    ) -> None:
        self._roles = {role.role_id: role for role in roles}
        self._assignments_by_user_domain: dict[tuple[str, str], list[RoleAssignment]] = defaultdict(list)
        self._policies_by_role: dict[str, list[PermissionPolicy]] = defaultdict(list)
        self._manageable_roles = manageable_roles or {}

        for assignment in assignments:
            self._assignments_by_user_domain[(assignment.user_id, assignment.tenant_id)].append(assignment)
        for policy in policies:
            self._policies_by_role[policy.role_id].append(policy)

    def get_role(self, role_id: str) -> Role | None:
        return self._roles.get(role_id)

    def upsert_role(self, role: Role) -> Role:
        self._roles[role.role_id] = role
        return role

    def list_roles(self, tenant_id: str | None = None) -> list[Role]:
        roles = self._roles.values()
        if tenant_id is not None:
            roles = [role for role in roles if role.tenant_id in (tenant_id, None, "*")]
        return sorted(roles, key=lambda role: (role.tenant_id or "", int(role.level), role.name))

    def list_user_assignments(self, user_id: str | None = None) -> list[RoleAssignment]:
        assignments = [
            assignment
            for items in self._assignments_by_user_domain.values()
            for assignment in items
            if user_id is None or assignment.user_id == user_id
        ]
        return sorted(assignments, key=lambda item: (item.user_id, item.tenant_id, item.role_id))

    def get_user_roles(self, user_id: str, tenant_id: str) -> list[RoleAssignment]:
        return [
            *self._assignments_by_user_domain.get((user_id, tenant_id), []),
            *self._assignments_by_user_domain.get((user_id, "*"), []),
        ]

    def replace_user_assignments(self, user_id: str, assignments: list[RoleAssignment]) -> None:
        self.delete_user_assignments(user_id)
        for assignment in assignments:
            self._assignments_by_user_domain[(assignment.user_id, assignment.tenant_id)].append(assignment)

    def delete_user_assignments(self, user_id: str) -> None:
        for key in [key for key in self._assignments_by_user_domain if key[0] == user_id]:
            del self._assignments_by_user_domain[key]

    def get_role_policies(self, role_id: str) -> list[PermissionPolicy]:
        return sorted(self._policies_by_role.get(role_id, []), key=lambda policy: policy.priority)

    def get_manageable_role_ids(self, role_id: str) -> set[str]:
        return set(self._manageable_roles.get(role_id, set()))

    def replace_role_policies(self, role_id: str, policies: list[PermissionPolicy]) -> None:
        self._policies_by_role[role_id] = list(policies)

    def replace_manageable_role_ids(self, role_id: str, manageable_role_ids: set[str]) -> None:
        self._manageable_roles[role_id] = set(manageable_role_ids)

    def seed(
        self,
        roles: Iterable[Role],
        assignments: Iterable[RoleAssignment],
        policies: Iterable[PermissionPolicy],
        manageable_roles: dict[str, set[str]] | None = None,
    ) -> None:
        for role in roles:
            self._roles[role.role_id] = role
        for assignment in assignments:
            key = (assignment.user_id, assignment.tenant_id)
            if assignment not in self._assignments_by_user_domain[key]:
                self._assignments_by_user_domain[key].append(assignment)
        for policy in policies:
            if policy not in self._policies_by_role[policy.role_id]:
                self._policies_by_role[policy.role_id].append(policy)
        if manageable_roles:
            for role_id, role_ids in manageable_roles.items():
                self._manageable_roles.setdefault(role_id, set()).update(role_ids)
