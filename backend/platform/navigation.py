from __future__ import annotations

from dataclasses import dataclass, field

from backend.authz.seed import MENU_TREE, MenuResource
from backend.platform.governance import PermissionBroker
from backend.platform.tenancy import ExecutionContext


@dataclass(frozen=True)
class NavigationItem:
    key: str
    label: str
    children: tuple["NavigationItem", ...] = field(default_factory=tuple)


def visible_navigation_tree(permission_broker: PermissionBroker, context: ExecutionContext) -> tuple[NavigationItem, ...]:
    """Build the menu tree visible for this user and tenant."""

    visible: list[NavigationItem] = []
    for item in MENU_TREE:
        resolved = _visible_item(item, permission_broker, context)
        if resolved is not None:
            visible.append(resolved)
    return tuple(visible)


def serialize_navigation(items: tuple[NavigationItem, ...]) -> list[dict]:
    return [
        {
            "key": item.key,
            "label": item.label,
            "children": serialize_navigation(item.children),
        }
        for item in items
    ]


def flatten_navigation_keys(items: tuple[NavigationItem, ...]) -> list[str]:
    keys: list[str] = []
    for item in items:
        keys.append(item.key)
        keys.extend(flatten_navigation_keys(item.children))
    return keys


def _visible_item(
    item: MenuResource,
    permission_broker: PermissionBroker,
    context: ExecutionContext,
) -> NavigationItem | None:
    if item.key == "task-workbench.message-board":
        if not permission_broker.enforcer.has_super_admin_role(context.user_id, context.tenant_id):
            return None
    children = tuple(
        child
        for child in (_visible_item(child, permission_broker, context) for child in item.children)
        if child is not None
    )
    can_read_self = permission_broker.check_resource(context, f"menu:{item.key}", "read")
    if not can_read_self and not children:
        return None
    return NavigationItem(key=item.key, label=item.label, children=children)
