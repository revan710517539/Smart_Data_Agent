from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


OPERATING_TENANTS = [
    "华兴银行",
    "广州银行",
    "兰州银行",
    "汉口银行",
    "石嘴山银行",
    "郑州银行",
    "临商银行",
    "瑞丰银行",
    "南京银行",
    "兴业消金",
    "三峡银行",
]


@dataclass(frozen=True)
class MenuResource:
    key: str
    label: str
    children: tuple["MenuResource", ...] = ()


MENU_TREE = (
    MenuResource("dashboard", "多机构分析"),
    MenuResource(
        "business-analysis",
        "经营分析",
        (
            MenuResource("business-analysis.weekly-report", "经营周报"),
            MenuResource("business-analysis.supervision", "机构督导"),
            MenuResource("business-analysis.customer-segment", "分客群分析"),
        ),
    ),
    MenuResource(
        "market-customer",
        "市场洞察",
        (
            MenuResource("market-customer.segment", "客群分析"),
            MenuResource("market-customer.competition", "竞品分析"),
        ),
    ),
    MenuResource(
        "self-analysis",
        "自助分析",
        (
            MenuResource("self-analysis.visual-reports", "可视化报表"),
            MenuResource("self-analysis.smart-analysis", "智能分析"),
            MenuResource("self-analysis.my-reports", "我的报表"),
            MenuResource("self-analysis.analysis-config", "分析配置"),
            MenuResource("task-workbench.skills", "skill/插件"),
        ),
    ),
    MenuResource(
        "task-workbench",
        "任务工作台",
        (
            MenuResource("task-workbench.todos", "待办任务"),
            MenuResource("task-workbench.tasks", "自动化任务"),
            MenuResource("task-workbench.message-board", "留言板管理"),
        ),
    ),
    MenuResource(
        "data-assets",
        "数据资产",
        (
            MenuResource("data-assets.metrics", "指标字典"),
            MenuResource("data-assets.knowledge", "知识记忆"),
            MenuResource("data-assets.data-management", "站内数据"),
            MenuResource("data-assets.quality", "质量监控"),
            MenuResource("data-assets.tools", "工具调用"),
        ),
    ),
    MenuResource(
        "notifications",
        "推送与订阅",
        (
            MenuResource("notifications.alerts", "预警规则"),
            MenuResource("notifications.subscriptions", "订阅管理"),
            MenuResource("notifications.history", "推送记录"),
        ),
    ),
    MenuResource(
        "settings",
        "系统管理",
        (
            MenuResource("settings.users", "用户管理"),
            MenuResource("settings.roles", "角色权限"),
            MenuResource("settings.audit", "审计日志"),
            MenuResource("settings.config", "系统配置"),
        ),
    ),
)

# System Management is a stable four-page workbench.  Do not let a saved role
# menu selection make audit or configuration disappear from its left navigation.
MANDATORY_MENU_KEYS = frozenset({"settings.audit", "settings.config"})
DEFAULT_ROLE_NAMES = ("管理员", "操作员")
CUSTOM_ROLE_CANDIDATES: tuple[str, ...] = ()
RETIRED_SEEDED_CUSTOM_ROLES = ("客户经理分析岗", "周报分析岗", "指标维护岗")
SUPER_ADMIN_OPT_IN_MENU_KEYS = frozenset({
    "dashboard",
    "market-customer",
    "market-customer.segment",
    "market-customer.competition",
    "task-workbench",
    "task-workbench.todos",
    "task-workbench.tasks",
    "task-workbench.message-board",
    "notifications",
    "notifications.alerts",
    "notifications.subscriptions",
    "notifications.history",
})


def flatten_menu_tree(menu_tree: Iterable[MenuResource] = MENU_TREE) -> dict[str, MenuResource]:
    resources: dict[str, MenuResource] = {}
    for item in menu_tree:
        resources[item.key] = item
        resources.update(flatten_menu_tree(item.children))
    return resources


def _parent_index(menu_tree: Iterable[MenuResource]) -> dict[str, str]:
    parents: dict[str, str] = {}
    for item in menu_tree:
        for child in item.children:
            parents[child.key] = item.key
        parents.update(_parent_index(item.children))
    return parents


def _children_index(menu_tree: Iterable[MenuResource]) -> dict[str, set[str]]:
    children: dict[str, set[str]] = {}
    for item in menu_tree:
        if item.children:
            children[item.key] = {child.key for child in item.children}
        children.update(_children_index(item.children))
    return children


def expand_menu_selection(selected_keys: Iterable[str]) -> set[str]:
    """Expand UI menu selections into the exact visible resource set.

    If a first-level menu is selected, all of its second-level menus are included.
    If only a second-level menu is selected, only that menu and its parent are shown.
    Audit logs and system config are always included for every role.
    """

    selected = set(selected_keys) | set(MANDATORY_MENU_KEYS)
    parent_by_child = _parent_index(MENU_TREE)
    children_by_parent = _children_index(MENU_TREE)
    known = flatten_menu_tree()
    expanded = set(MANDATORY_MENU_KEYS)

    for key in selected:
        if key not in known:
            continue
        expanded.add(key)
        if key in children_by_parent:
            expanded.update(children_by_parent[key])
        parent = parent_by_child.get(key)
        if parent:
            expanded.add(parent)

    return expanded
