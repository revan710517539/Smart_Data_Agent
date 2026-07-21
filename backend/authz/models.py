from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Literal


Effect = Literal["allow", "deny"]


class RoleLevel(IntEnum):
    OPERATOR = 10
    TENANT_ADMIN = 50
    SUPER_ADMIN = 100


@dataclass(frozen=True)
class AuthRequest:
    """Casbin-like request tuple: r = sub, dom, obj, act, attrs."""

    sub: str
    dom: str
    obj: str
    act: str
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Role:
    role_id: str
    tenant_id: str | None
    name: str
    level: RoleLevel
    is_system: bool = False
    created_by: str | None = None

    @property
    def is_global(self) -> bool:
        return self.tenant_id in (None, "*")


@dataclass(frozen=True)
class RoleAssignment:
    user_id: str
    tenant_id: str
    role_id: str
    granted_by: str | None = None


@dataclass(frozen=True)
class PermissionPolicy:
    """Casbin-like policy tuple: p = sub, dom, obj, act, eft, attrs."""

    role_id: str
    tenant_id: str | None
    obj: str
    act: str
    effect: Effect = "allow"
    attrs: dict[str, Any] = field(default_factory=dict)
    priority: int = 100

    @property
    def is_global(self) -> bool:
        return self.tenant_id in (None, "*")


@dataclass(frozen=True)
class MetricAccessDecision:
    allowed: bool
    allowed_metric_ids: set[str] = field(default_factory=set)
    allowed_fields: set[str] = field(default_factory=set)
    row_filter: dict[str, Any] = field(default_factory=dict)
