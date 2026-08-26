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

    is_super_admin = permission_broker.enforcer.has_super_admin_role(context.user_id, context.tenant_id)
    if is_super_admin:
        return _full_navigation_tree(MENU_TREE)
    show_dashboard = _user_has_multiple_institutions(permission_broker, context)
    visible: list[NavigationItem] = []
    for item in MENU_TREE:
        if item.key == "dashboard":
            if show_dashboard:
                visible.append(NavigationItem(key=item.key, label=item.label))
            continue
        resolved = _visible_item(item, permission_broker, context)
        if resolved is not None:
            visible.append(resolved)
    return tuple(visible)


def _full_navigation_tree(items: tuple[MenuResource, ...]) -> tuple[NavigationItem, ...]:
    return tuple(NavigationItem(key=item.key, label=item.label, children=_full_navigation_tree(item.children)) for item in items)


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


def _user_has_multiple_institutions(permission_broker: PermissionBroker, context: ExecutionContext) -> bool:
    enforcer = permission_broker.enforcer
    if enforcer.has_super_admin_role(context.user_id, context.tenant_id):
        return True
    tenants = {
        assignment.tenant_id
        for assignment in enforcer.repository.list_user_assignments(context.user_id)
        if assignment.tenant_id and assignment.tenant_id != "*"
    }
    return len(tenants) >= 2


def _visible_item(
    item: MenuResource,
    permission_broker: PermissionBroker,
    context: ExecutionContext,
) -> NavigationItem | None:
    if item.key in {"task-workbench.message-board", "task-workbench.interaction-analytics"}:
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
