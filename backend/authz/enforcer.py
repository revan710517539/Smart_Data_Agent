from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any

from .models import AuthRequest, MetricAccessDecision, PermissionPolicy, Role, RoleLevel
from .repository import PolicyRepository


class AuthEnforcer:
    """Native PERM/RBAC/ABAC enforcer.

    Model:
        r = sub, dom, obj, act, attrs
        p = role_id, dom, obj, act, eft, attrs
        g = user, role, dom
        e = deny overrides allow, then any allow
        m = g(r.sub, p.sub, r.dom) and domain/object/action/attribute match
    """

    def __init__(self, repository: PolicyRepository) -> None:
        self.repository = repository

    def enforce(
        self,
        user_id: str,
        tenant_id: str,
        resource: str,
        action: str,
        resource_attrs: dict[str, Any] | None = None,
    ) -> bool:
        request = AuthRequest(
            sub=user_id,
            dom=tenant_id,
            obj=resource,
            act=action,
            attrs=resource_attrs or {},
        )
        return self._enforce_request(request)

    def _enforce_request(self, request: AuthRequest) -> bool:
        if self._has_super_admin_role(request.sub, request.dom):
            return True
        matched_allows = False
        for role in self._load_roles(request.sub, request.dom):
            for policy in self.repository.get_role_policies(role.role_id):
                if not self._policy_matches(request, policy):
                    continue
                if policy.effect == "deny":
                    return False
                matched_allows = True
        return matched_allows

    def _has_super_admin_role(self, user_id: str, tenant_id: str) -> bool:
        return any(role.level == RoleLevel.SUPER_ADMIN for role in self._load_roles(user_id, tenant_id))

    def has_super_admin_role(self, user_id: str, tenant_id: str) -> bool:
        """Return whether the authenticated subject has a global super-admin role."""

        return self._has_super_admin_role(user_id, tenant_id)

    def can_manage_role(self, user_id: str, tenant_id: str, target_role_id: str) -> bool:
        target = self.repository.get_role(target_role_id)
        if not target:
            return False

        for role in self._load_roles(user_id, tenant_id):
            if role.level == RoleLevel.SUPER_ADMIN:
                return True
            if role.tenant_id != tenant_id or target.tenant_id != tenant_id:
                continue
            if target_role_id in self.repository.get_manageable_role_ids(role.role_id) and role.level >= target.level:
                return True
            if not target.is_system and target.created_by in (role.role_id, user_id) and role.level >= target.level:
                return True
        return False

    def metric_access(
        self,
        user_id: str,
        tenant_id: str,
        metric_ids: set[str],
        requested_fields: set[str],
        metric_attrs: dict[str, Any] | None = None,
    ) -> MetricAccessDecision:
        attrs = {
            "resource_type": "metric",
            "tenant_id": tenant_id,
            "metric_ids": metric_ids,
            "fields": requested_fields,
            **(metric_attrs or {}),
        }
        if not self.enforce(user_id, tenant_id, "metric:*", "read", attrs):
            return MetricAccessDecision(allowed=False)

        allowed_metric_ids = set(metric_ids)
        allowed_fields = set(requested_fields)
        row_filter: dict[str, Any] = {"tenant_id": tenant_id}

        for role in self._load_roles(user_id, tenant_id):
            for policy in self.repository.get_role_policies(role.role_id):
                if not self._policy_matches(AuthRequest(user_id, tenant_id, "metric:*", "read", attrs), policy):
                    continue
                if "metric_ids" in policy.attrs:
                    allowed_metric_ids &= set(policy.attrs["metric_ids"])
                if "fields" in policy.attrs:
                    allowed_fields &= set(policy.attrs["fields"])
                row_filter.update(policy.attrs.get("row_filter", {}))

        return MetricAccessDecision(
            allowed=True,
            allowed_metric_ids=allowed_metric_ids,
            allowed_fields=allowed_fields,
            row_filter=row_filter,
        )

    def _load_roles(self, user_id: str, tenant_id: str) -> list[Role]:
        roles: list[Role] = []
        for assignment in self.repository.get_user_roles(user_id, tenant_id):
            role = self.repository.get_role(assignment.role_id)
            if role and (role.is_global or role.tenant_id == tenant_id):
                roles.append(role)
        return roles

    def _policy_matches(self, request: AuthRequest, policy: PermissionPolicy) -> bool:
        return (
            self._domain_matches(request.dom, policy.tenant_id)
            and self._object_matches(request.obj, policy.obj)
            and self._action_matches(request.act, policy.act)
            and self._attributes_match(request.attrs, policy.attrs)
        )

    @staticmethod
    def _domain_matches(request_domain: str, policy_domain: str | None) -> bool:
        return policy_domain in (None, "*", request_domain)

    @staticmethod
    def _object_matches(request_object: str, policy_object: str) -> bool:
        return policy_object == "*" or fnmatchcase(request_object, policy_object)

    @staticmethod
    def _action_matches(request_action: str, policy_action: str) -> bool:
        return policy_action == "*" or request_action == policy_action

    @staticmethod
    def _attributes_match(request_attrs: dict[str, Any], policy_attrs: dict[str, Any]) -> bool:
        if not policy_attrs:
            return True

        required_tenant = policy_attrs.get("tenant_id")
        if required_tenant and request_attrs.get("tenant_id") not in (None, required_tenant):
            return False

        required_resource_type = policy_attrs.get("resource_type")
        if required_resource_type and request_attrs.get("resource_type") != required_resource_type:
            return False

        allowed_metrics = policy_attrs.get("metric_ids")
        requested_metrics = request_attrs.get("metric_ids")
        if allowed_metrics is not None and requested_metrics is not None:
            if not set(requested_metrics).issubset(set(allowed_metrics)):
                return False

        allowed_fields = policy_attrs.get("fields")
        requested_fields = request_attrs.get("fields")
        if allowed_fields is not None and requested_fields is not None:
            if not set(requested_fields).issubset(set(allowed_fields)):
                return False

        row_filter = policy_attrs.get("row_filter", {})
        for key, expected_value in row_filter.items():
            if key in request_attrs and request_attrs[key] != expected_value:
                return False

        return True
