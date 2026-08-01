import { useEffect, useMemo, useState, type ComponentType } from "react";
import { Navigate, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import {
  BarChart3,
  Gauge,
  Search,
  BrainCircuit,
  Database,
  Bell,
  Settings,
  ChevronDown,
  ChevronRight,
  Landmark,
  ListChecks,
  LogOut,
  X,
  Sparkles,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { runApplicationAction } from "../services/applicationApi";
import { fetchNavigation } from "../services/navigationApi";
import { preloadRoutePath } from "../routePreload";
import { AgentSupervisor } from "./agent-supervisor/AgentSupervisor";

type MenuItem = {
  key: string;
  path?: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  children?: Omit<MenuItem, "icon">[];
};

const menuItems: MenuItem[] = [
  { key: "dashboard", path: "/", label: "多机构分析", icon: Gauge },
  {
    key: "business-analysis",
    label: "经营分析",
    icon: BarChart3,
    children: [
      { key: "business-analysis.weekly-report", path: "/weekly-report", label: "经营周报" },
      { key: "business-analysis.supervision", path: "/supervision", label: "机构督导" },
    ],
  },
  {
    key: "self-analysis",
    label: "自助分析",
    icon: Search,
    children: [
      { key: "self-analysis.smart-analysis", path: "/self-analysis/query", label: "智能分析" },
      { key: "self-analysis.my-reports", path: "/self-analysis/reports", label: "我的报告" },
      { key: "self-analysis.analysis-config", path: "/self-analysis/config", label: "分析配置" },
    ],
  },
  {
    key: "task-workbench",
    label: "任务工作台",
    icon: BrainCircuit,
    children: [
      { key: "task-workbench.todos", path: "/agent/todos", label: "待办任务" },
      { key: "task-workbench.tasks", path: "/agent/tasks", label: "自动化任务" },
      { key: "task-workbench.skills", path: "/agent/skills", label: "Skill插件" },
    ],
  },
  {
    key: "data-assets",
    label: "数据资产",
    icon: Database,
    children: [
      { key: "data-assets.metrics", path: "/data-assets/metrics", label: "指标字典" },
      { key: "data-assets.knowledge", path: "/data-assets/knowledge", label: "知识记忆" },
      { key: "data-assets.data-management", path: "/data-assets/data-management", label: "数据管理" },
      { key: "data-assets.quality", path: "/data-assets/quality", label: "质量监控" },
      { key: "data-assets.tools", path: "/data-assets/tools", label: "工具调用" },
    ],
  },
  {
    key: "notifications",
    label: "推送与订阅",
    icon: Bell,
    children: [
      { key: "notifications.alerts", path: "/notifications/alerts", label: "预警规则" },
      { key: "notifications.subscriptions", path: "/notifications/subscriptions", label: "订阅管理" },
      { key: "notifications.history", path: "/notifications/history", label: "推送记录" },
    ],
  },
  {
    key: "settings",
    label: "系统管理",
    icon: Settings,
    children: [
      { key: "settings.users", path: "/settings/users", label: "用户管理" },
      { key: "settings.roles", path: "/settings/roles", label: "角色权限" },
      { key: "settings.audit", path: "/settings/audit", label: "审计日志" },
      { key: "settings.config", path: "/settings/config", label: "系统配置" },
    ],
  },
];

export function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const {
    currentTenantRoles,
    institutions,
    isAuthenticated,
    logout,
    selectedInstitution,
    setSelectedInstitution,
    tenantId,
    userId,
    userName,
  } = usePlatformContext();
  const [expandedMenus, setExpandedMenus] = useState<string[]>([]);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarEdgeVisible, setSidebarEdgeVisible] = useState(false);
  const [sidebarEdgeY, setSidebarEdgeY] = useState(() => Math.round(window.innerHeight / 2));
  const [allowedMenuKeys, setAllowedMenuKeys] = useState<Set<string> | null>(new Set());
  const [navigationStatus, setNavigationStatus] = useState<"loading" | "ready" | "failed">("loading");
  const [institutionOpen, setInstitutionOpen] = useState(false);
  const [todoReturnPath, setTodoReturnPath] = useState("/");

  useEffect(() => {
    let cancelled = false;
    const loadNavigation = async () => {
      setNavigationStatus("loading");
      setAllowedMenuKeys(new Set());
      try {
        const response = await fetchNavigation({ tenantId, userId });
        if (!cancelled) {
          setAllowedMenuKeys(new Set(response.menu_keys));
          setNavigationStatus("ready");
        }
      } catch {
        if (!cancelled) {
          setAllowedMenuKeys(new Set());
          setNavigationStatus("failed");
        }
      }
    };
    void loadNavigation();
    return () => {
      cancelled = true;
    };
  }, [tenantId, userId]);

  const visibleMenuItems = useMemo(
    () => filterMenuItems(menuItems, allowedMenuKeys),
    [allowedMenuKeys],
  );
  const currentMenuKey = menuKeyForPath(menuItems, location.pathname);
  const accessFallbackPath = firstAllowedMenuPath(menuItems, allowedMenuKeys) || "/";
  const isTodoPage = location.pathname === "/agent/todos";

  useEffect(() => {
    if (!isTodoPage) {
      setTodoReturnPath(`${location.pathname}${location.search}${location.hash}` || "/");
    }
  }, [isTodoPage, location.hash, location.pathname, location.search]);

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  if (
    navigationStatus === "ready" &&
    currentMenuKey &&
    allowedMenuKeys &&
    !allowedMenuKeys.has(currentMenuKey)
  ) {
    return <Navigate to={accessFallbackPath} replace />;
  }

  const toggleMenu = (label: string) => {
    setExpandedMenus((prev) =>
      prev.includes(label) ? prev.filter((m) => m !== label) : [...prev, label]
    );
  };

  const runShellAction = (action: string, payload: Record<string, unknown> = {}) =>
    runApplicationAction({ tenantId, userId, moduleKey: "platform_shell", action, payload });

  const handleTodoShortcut = () => {
    navigate(isTodoPage ? todoReturnPath || "/" : "/agent/todos");
  };

  return (
    <div className="flex h-screen bg-white overflow-hidden">
      {sidebarCollapsed ? (
        <div
          className="fixed bottom-0 left-0 top-0 z-[60] hidden w-10 lg:block"
          data-agent-sidebar-expand-zone="true"
          onMouseEnter={(event) => {
            setSidebarEdgeVisible(true);
            setSidebarEdgeY(event.clientY);
          }}
          onMouseMove={(event) => {
            setSidebarEdgeVisible(true);
            setSidebarEdgeY(event.clientY);
          }}
          onMouseLeave={() => setSidebarEdgeVisible(false)}
        >
          <button
            type="button"
            onClick={() => setSidebarCollapsed(false)}
            aria-label="展开左侧菜单"
            title="展开菜单"
            data-agent-sidebar-expand="true"
            className={`fixed left-2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full border border-[#d9d9de] bg-white/95 text-[#636366] shadow-lg shadow-black/10 backdrop-blur transition-all duration-150 hover:bg-[#f2f2f7] hover:text-[#1d1d1f] ${sidebarEdgeVisible ? "scale-100 opacity-100" : "pointer-events-none scale-90 opacity-0"}`}
            style={{ top: Math.max(28, Math.min(window.innerHeight - 28, sidebarEdgeY)) }}
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        </div>
      ) : null}
      {/* Sidebar — macOS-style light */}
      <aside data-agent-sidebar="true" data-collapsed={sidebarCollapsed ? "true" : "false"} className={`hidden lg:flex bg-[#fafbfc] flex-col shrink-0 overflow-hidden transition-[width,border-color] duration-200 ease-out ${sidebarCollapsed ? "lg:w-0" : "lg:w-[216px] border-r border-[#ebebf0]"}`}>
        {!sidebarCollapsed ? <>
        {/* Logo */}
        <div className="px-5 pt-6 pb-4">
          <div className="flex w-full items-start gap-2">
            <div className="flex min-w-0 items-center gap-2">
              <div className="w-[26px] h-[26px] rounded-md bg-[#1d1d1f] flex items-center justify-center" data-agent-logo-mark="true">
                <Sparkles className="w-3.5 h-3.5 text-white" />
              </div>
              <div>
                <span className="text-[14px] text-[#1d1d1f] tracking-tight">
                  Data Agent
                </span>
                <div className="text-[10px] text-[#aeaeb2]">消费贷 · 经营贷</div>
              </div>
            </div>
            <div className="ml-auto mt-[6.5px] flex items-center gap-1">
              <button
                type="button"
                onClick={handleTodoShortcut}
                aria-label={isTodoPage ? "返回上一页" : "打开待办任务"}
                title={isTodoPage ? "返回上一页" : "待办任务"}
                data-agent-todo-shortcut="true"
                className={`flex h-[26px] w-[26px] items-center justify-center rounded-md border transition-colors ${
                  isTodoPage
                    ? "border-[#d1d1d6] bg-[#f2f2f7] text-[#1d1d1f]"
                    : "border-[#e5e5ea] bg-[#fafbfc] text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"
                }`}
              >
                <ListChecks className="h-3.5 w-3.5" />
              </button>
              <button type="button" onClick={() => setSidebarCollapsed(true)} aria-label="收起左侧菜单" title="收起菜单" data-agent-sidebar-collapse="true" className="flex h-[26px] w-[26px] items-center justify-center rounded-md border border-[#e5e5ea] bg-[#fafbfc] text-[#8a8a8e] transition-colors hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"><PanelLeftClose className="h-3.5 w-3.5" /></button>
            </div>
          </div>
          <div className="relative mt-3">
            <button
              type="button"
              onClick={() => setInstitutionOpen((open) => !open)}
              className="flex h-8 w-full items-center gap-2 rounded-lg border border-[#e5e5ea] bg-white px-2.5 text-[12px] text-[#3a3a3c] transition-colors hover:bg-[#f2f2f7]"
              aria-expanded={institutionOpen}
            >
              <Landmark className="h-3.5 w-3.5 text-[#8a8a8e]" />
              <span className="min-w-0 flex-1 truncate text-left">{selectedInstitution}</span>
              <ChevronDown className={`h-3 w-3 text-[#aeaeb2] transition-transform ${institutionOpen ? "rotate-180" : ""}`} />
            </button>
            {institutionOpen && (
              <div className="absolute left-0 right-0 top-9 z-40 rounded-lg border border-[#e5e5ea] bg-white p-1 shadow-lg shadow-black/[0.08]">
                {institutions.map((institution) => (
                  <button
                    key={institution}
                    type="button"
                    onClick={() => {
                      setSelectedInstitution(institution);
                      setInstitutionOpen(false);
                      void runShellAction("select_institution", { selectedInstitution: institution });
                    }}
                    className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[12px] ${
                      selectedInstitution === institution
                        ? "bg-[#f2f2f7] text-[#1d1d1f]"
                        : "text-[#636366] hover:bg-[#fafbfc]"
                    }`}
                  >
                    <Landmark className="h-3.5 w-3.5 text-[#8a8a8e]" />
                    {institution}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 overflow-y-auto">
          {visibleMenuItems.map((item) => {
            if (item.children) {
              const isExpanded = expandedMenus.includes(item.label);
              return (
                <div key={item.label} className="mb-px">
                  <button
                    onClick={() => toggleMenu(item.label)}
                    className="w-full flex items-center gap-2 px-2.5 py-[7px] text-[#8a8a8e] hover:text-[#3a3a3c] rounded-md hover:bg-black/[0.03] transition-colors text-[13px]"
                  >
                    <item.icon className="w-[15px] h-[15px] opacity-60" />
                    <span className="flex-1 text-left">{item.label}</span>
                    <ChevronRight
                      className={`w-3 h-3 opacity-40 transition-transform ${isExpanded ? "rotate-90" : ""}`}
                    />
                  </button>
                  {isExpanded && (
                    <div className="ml-[23px] border-l border-[#e5e5ea] pl-2.5 mt-px mb-1">
                      {item.children.map((child) => (
                        <NavLink
                          key={child.path}
                          to={child.path}
                          onMouseEnter={() => preloadRoutePath(child.path || "")}
                          onFocus={() => preloadRoutePath(child.path || "")}
                          className={({ isActive }) =>
                            `flex items-center px-2.5 py-[6px] text-[13px] rounded-md transition-colors ${
                              isActive
                                ? "text-[#1d1d1f] bg-black/[0.05]"
                                : "text-[#8a8a8e] hover:text-[#3a3a3c] hover:bg-black/[0.03]"
                            }`
                          }
                        >
                          {child.label}
                        </NavLink>
                      ))}
                    </div>
                  )}
                </div>
              );
            }
            return (
              <NavLink
                key={item.path}
                to={item.path!}
                className={({ isActive }) =>
                  `flex items-center gap-2 px-2.5 py-[7px] text-[13px] rounded-md transition-colors mb-px ${
                    isActive
                      ? "text-[#1d1d1f] bg-black/[0.05]"
                      : "text-[#8a8a8e] hover:text-[#3a3a3c] hover:bg-black/[0.03]"
                  }`
                }
              >
                <item.icon className="w-[15px] h-[15px] opacity-50" />
                {item.label}
              </NavLink>
            );
          })}
        </nav>

        {/* User */}
        <div className="px-4 py-3.5 border-t border-[#ebebf0]">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-full bg-[#ebebf0] flex items-center justify-center text-[11px] text-[#636366]">
              {userName[0] || "用"}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[12px] text-[#3a3a3c]">{userName}</div>
              <div className="truncate text-[11px] text-[#aeaeb2]">
                {selectedInstitution} · {currentTenantRoles.map((role) => role.role).join("、") || "未授权"}
              </div>
            </div>
            <button
              type="button"
              onClick={logout}
              className="rounded-md p-1.5 text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"
              aria-label="退出登录"
            >
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
        </> : null}
      </aside>

      {/* Main */}
      <main data-agent-main-shell="true" className="flex-1 min-w-0 overflow-y-auto bg-[#f8f8fa]">
        {navigationStatus === "loading" ? (
          <div className="p-7 text-[13px] text-[#8a8a8e]">正在校验页面权限...</div>
        ) : navigationStatus === "failed" ? (
          <div className="m-7 rounded-xl border border-[#ffd7d7] bg-[#fff5f5] px-4 py-3 text-[13px] text-[#b42318]">
            页面权限加载失败，请确认登录状态后刷新页面。
          </div>
        ) : (
          <Outlet />
        )}
      </main>

      <AgentSupervisor />
    </div>
  );
}

function filterMenuItems(items: MenuItem[], allowedKeys: Set<string> | null): MenuItem[] {
  if (!allowedKeys) return items;
  return items
    .map((item) => {
      const children = item.children?.filter((child) => allowedKeys.has(child.key));
      if (!allowedKeys.has(item.key) && !children?.length) return null;
      return children ? { ...item, children } : item;
    })
    .filter((item): item is MenuItem => item !== null);
}

function menuKeyForPath(items: MenuItem[], pathname: string): string | null {
  const normalizedPath = pathname.length > 1 ? pathname.replace(/\/$/, "") : pathname;
  for (const item of items) {
    if (item.path === normalizedPath) return item.key;
    const child = item.children?.find((candidate) => candidate.path === normalizedPath);
    if (child) return child.key;
  }
  return null;
}

function firstAllowedMenuPath(items: MenuItem[], allowedKeys: Set<string> | null): string | null {
  if (!allowedKeys) return null;
  for (const item of items) {
    if (item.path && allowedKeys.has(item.key)) return item.path;
    const child = item.children?.find((candidate) => candidate.path && allowedKeys.has(candidate.key));
    if (child?.path) return child.path;
  }
  return null;
}
