from __future__ import annotations

from typing import Any

from backend.authz import AuthEnforcer
from backend.platform.tenancy import ExecutionContext


class PermissionBroker:
    """Central permission facade for platform capabilities."""

    def __init__(self, enforcer: AuthEnforcer) -> None:
        self.enforcer = enforcer

    def check_resource(
        self,
        context: ExecutionContext,
        resource: str,
        action: str,
        attrs: dict[str, Any] | None = None,
    ) -> bool:
        return self.enforcer.enforce(
            user_id=context.user_id,
            tenant_id=context.tenant_id,
            resource=resource,
            action=action,
            resource_attrs={"tenant_id": context.tenant_id, **(attrs or {})},
        )

    def require_resource(
        self,
        context: ExecutionContext,
        resource: str,
        action: str,
        attrs: dict[str, Any] | None = None,
    ) -> None:
        if not self.check_resource(context, resource, action, attrs):
            raise PermissionError(f"Permission denied: {resource}:{action}")

    def require_skill(self, context: ExecutionContext, skill_id: str) -> None:
        self.require_resource(context, f"skill:{skill_id}", "execute")

