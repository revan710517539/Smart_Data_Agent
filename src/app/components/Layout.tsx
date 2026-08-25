import { startTransition, useEffect, useMemo, useRef, useState, type ComponentType } from "react";
import { Navigate, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import {
  BarChart3,
  FileChartColumn,
  Gauge,
  Search,
  BrainCircuit,
  Database,
  Bell,
  PieChart,
  Settings,
  ChevronDown,
  ChevronRight,
  Landmark,
  ListChecks,
  KeyRound,
  LogOut,
  X,
  Sparkles,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { runApplicationAction } from "../services/applicationApi";
import { fetchNavigation } from "../services/navigationApi";
import { prepareRoutePath, preloadRoutePath, warmVisibleRoutePaths } from "../routePreload";
import { preloadRouteDataPath } from "../routeDataPreload";
import { AgentSupervisor } from "./agent-supervisor/AgentSupervisor";
import { contextRailWideEvent } from "./context-rail/ContextSideRail";
import { GlobalContextRail } from "./context-rail/GlobalContextRail";
import { GlobalMessageBoardShortcut } from "./message-board/GlobalMessageBoardShortcut";
import { fetchSystemConfig } from "../services/systemConfigApi";
import {
  configuredTextModelOptions,
  persistTextModelSelection,
  readPersistedTextModelSelection,
  type TextModelOption,
} from "../services/modelSelectionStore";
import { trackInteraction } from "../services/interactionTelemetry";
import { changeAccountPassword } from "../services/authApi";
import { apiErrorMessage } from "../services/apiClient";

type MenuItem = {
  key: string;
  path?: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  children?: Omit<MenuItem, "icon">[];
};

const menuItems: MenuItem[] = [
  { key: "dashboard", path: "/dashboard", label: "多机构分析", icon: Gauge },
  {
    key: "business-analysis",
    label: "经营分析",
    icon: BarChart3,
    children: [
      { key: "business-analysis.weekly-report", path: "/weekly-report", label: "经营周报" },
      { key: "business-analysis.supervision", path: "/supervision", label: "机构督导" },
      { key: "business-analysis.customer-segment", path: "/customer-segment-analysis", label: "分客群分析" },
    ],
  },
  {
    key: "market-customer",
    label: "市场洞察",
    icon: PieChart,
    children: [
      { key: "market-customer.segment", path: "/customers", label: "客群分析" },
      { key: "market-customer.competition", path: "/competition", label: "竞品分析" },
    ],
  },
  { key: "self-analysis.my-reports", path: "/self-analysis/reports", label: "我的报表", icon: FileChartColumn },
  {
    key: "self-analysis",
    label: "自助分析",
    icon: Search,
    children: [
      { key: "self-analysis.visual-reports", path: "/self-analysis/visual-reports", label: "可视化报表" },
      { key: "self-analysis.smart-analysis", path: "/self-analysis/query", label: "智能分析" },
      { key: "self-analysis.analysis-config", path: "/self-analysis/config", label: "分析配置" },
      { key: "task-workbench.skills", path: "/agent/skills", label: "skill/插件" },
    ],
  },
  {
    key: "task-workbench",
    label: "任务工作台",
    icon: BrainCircuit,
    children: [
      { key: "task-workbench.todos", path: "/agent/todos", label: "待办任务" },
      { key: "task-workbench.tasks", path: "/agent/tasks", label: "自动化任务" },
      { key: "task-workbench.message-board", path: "/agent/message-board", label: "留言板管理" },
    ],
  },
  {
    key: "data-assets",
    label: "数据资产",
    icon: Database,
    children: [
      { key: "data-assets.metrics", path: "/data-assets/metrics", label: "指标字典" },
      { key: "data-assets.knowledge", path: "/data-assets/knowledge", label: "知识记忆" },
      { key: "data-assets.data-management", path: "/data-assets/data-management", label: "站内数据" },
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
    isSuperAdmin,
    logout,
    selectedInstitution,
    setSelectedInstitution,
    tenantId,
    userId,
    userName,
  } = usePlatformContext();
  const [expandedMenus, setExpandedMenus] = useState<string[]>([]);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const sidebarCollapsedRef = useRef(false);
  const sidebarCollapsedBeforeWideRef = useRef(false);
  const contextRailWideRef = useRef(false);
  const routeWarmupCancelRef = useRef<() => void>(() => undefined);
  const routeIntentGenerationRef = useRef(0);
  const [sidebarEdgeVisible, setSidebarEdgeVisible] = useState(false);
  const [pendingRoutePath, setPendingRoutePath] = useState("");
  const [allowedMenuKeys, setAllowedMenuKeys] = useState<Set<string> | null>(() => {
    if (isSuperAdmin) return new Set(allMenuKeys(menuItems));
    const cached = readCachedNavigation(userId, tenantId);
    return cached.length ? new Set(cached) : new Set();
  });
  const [navigationStatus, setNavigationStatus] = useState<"loading" | "ready" | "failed">(() => {
    if (isSuperAdmin) return "ready";
    return readCachedNavigation(userId, tenantId).length ? "ready" : "loading";
  });
  const [institutionOpen, setInstitutionOpen] = useState(false);
  const [todoReturnPath, setTodoReturnPath] = useState("/");
  const [textModelOptions, setTextModelOptions] = useState<TextModelOption[]>([]);
  const [selectedTextModelId, setSelectedTextModelId] = useState("");
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [passwordNotice, setPasswordNotice] = useState("");
  const [passwordSaving, setPasswordSaving] = useState(false);

  useEffect(() => {
    if (!isAuthenticated) {
      setAllowedMenuKeys(new Set());
      setNavigationStatus("loading");
      return;
    }
    let cancelled = false;
    const optimisticKeys = isSuperAdmin ? allMenuKeys(menuItems) : readCachedNavigation(userId, tenantId);
    if (optimisticKeys.length) {
      setAllowedMenuKeys(new Set(optimisticKeys));
      setNavigationStatus("ready");
    } else {
      setNavigationStatus("loading");
    }
    const loadNavigation = async () => {
      let lastError: unknown;
      for (let attempt = 0; attempt < 3; attempt += 1) {
        try {
          const response = await fetchNavigation({ tenantId, userId });
          if (cancelled) return;
          const keys = Array.isArray(response.menu_keys) ? response.menu_keys : [];
          setAllowedMenuKeys(new Set(keys));
          setNavigationStatus("ready");
          writeCachedNavigation(userId, tenantId, keys);
          return;
        } catch (error) {
          lastError = error;
          if (attempt < 2) await new Promise((resolve) => window.setTimeout(resolve, 400 * (attempt + 1)));
        }
      }
      if (!cancelled && !optimisticKeys.length) {
        setAllowedMenuKeys(new Set());
        setNavigationStatus("failed");
        console.warn("navigation_load_failed", lastError);
      }
    };
    void loadNavigation();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, isSuperAdmin, tenantId, userId]);

  useEffect(() => {
    sidebarCollapsedRef.current = sidebarCollapsed;
  }, [sidebarCollapsed]);

  useEffect(() => {
    const handleWideRail = (event: Event) => {
      const wide = Boolean((event as CustomEvent<{ wide?: boolean }>).detail?.wide);
      if (wide && !contextRailWideRef.current) {
        sidebarCollapsedBeforeWideRef.current = sidebarCollapsedRef.current;
        setSidebarCollapsed(true);
      } else if (!wide && contextRailWideRef.current) {
        setSidebarCollapsed(sidebarCollapsedBeforeWideRef.current);
      }
      contextRailWideRef.current = wide;
    };
    window.addEventListener(contextRailWideEvent, handleWideRail);
    return () => window.removeEventListener(contextRailWideEvent, handleWideRail);
  }, []);

  const visibleMenuItems = useMemo(
    () => filterMenuItems(menuItems, allowedMenuKeys, institutions.length),
    [allowedMenuKeys, institutions.length],
  );
  const currentMenuKey = menuKeyForPath(menuItems, location.pathname);
  const accessFallbackPath = firstVisibleMenuPath(visibleMenuItems) || "/";
  const isTodoPage = location.pathname === "/agent/todos";
  const isSmartAnalysisPage = location.pathname === "/self-analysis/query";

  useEffect(() => {
    if (!isAuthenticated || navigationStatus !== "ready") return;
    const visiblePaths = visibleMenuItems.flatMap((item) => [
      ...(item.path ? [item.path] : []),
      ...(item.children?.flatMap((child) => child.path ? [child.path] : []) || []),
    ]);
    routeWarmupCancelRef.current();
    const cancelCodeWarmup = warmVisibleRoutePaths(visiblePaths, location.pathname);
    routeWarmupCancelRef.current = cancelCodeWarmup;
    let dashboardIdleId: number | null = null;
    let dashboardTimeoutId: number | null = null;
    const warmDashboardData = () => {
      dashboardIdleId = null;
      dashboardTimeoutId = null;
      preloadRouteDataPath("/dashboard", { tenantId, userId });
    };
    if (location.pathname !== "/dashboard" && visiblePaths.includes("/dashboard")) {
      if (typeof window.requestIdleCallback === "function") {
        dashboardIdleId = window.requestIdleCallback(warmDashboardData, { timeout: 800 });
      } else {
        dashboardTimeoutId = window.setTimeout(warmDashboardData, 180);
      }
    }
    return () => {
      cancelCodeWarmup();
      if (routeWarmupCancelRef.current === cancelCodeWarmup) routeWarmupCancelRef.current = () => undefined;
      if (dashboardIdleId !== null && typeof window.cancelIdleCallback === "function") window.cancelIdleCallback(dashboardIdleId);
      if (dashboardTimeoutId !== null) window.clearTimeout(dashboardTimeoutId);
    };
  }, [isAuthenticated, location.pathname, navigationStatus, tenantId, userId, visibleMenuItems]);

  useEffect(() => {
    routeIntentGenerationRef.current += 1;
    setPendingRoutePath("");
  }, [location.pathname, tenantId, userId]);

  useEffect(() => {
    const parent = menuItems.find((item) => item.children?.some((child) => child.path === location.pathname));
    if (!parent) return;
    setExpandedMenus((current) => current.includes(parent.label) ? current : [...current, parent.label]);
  }, [location.pathname]);

  useEffect(() => {
    if (!isAuthenticated || isSmartAnalysisPage) {
      setTextModelOptions([]);
      setSelectedTextModelId("");
      return;
    }
    let cancelled = false;
    const syncTextModels = async () => {
      try {
        const response = await fetchSystemConfig({ tenantId, userId });
        if (cancelled) return;
        const options = configuredTextModelOptions(response.models);
        const persisted = readPersistedTextModelSelection(tenantId, userId);
        const selected = options.find((option) => option.id === `${persisted?.integrationId || ""}::${persisted?.selectedModelName || ""}`)
          || options[0];
        setTextModelOptions(options);
        setSelectedTextModelId(selected?.id || "");
        if (selected && selected.id !== `${persisted?.integrationId || ""}::${persisted?.selectedModelName || ""}`) {
          persistTextModelSelection(tenantId, userId, selected);
        }
      } catch {
        if (!cancelled) {
          setTextModelOptions([]);
          setSelectedTextModelId("");
        }
      }
    };
    void syncTextModels();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, isSmartAnalysisPage, tenantId, userId]);

  useEffect(() => {
    if (!isTodoPage) {
      setTodoReturnPath(`${location.pathname}${location.search}${location.hash}` || "/");
    }
  }, [isTodoPage, location.hash, location.pathname, location.search]);

  useEffect(() => {
    if (!isAuthenticated) return;
    trackInteraction({ eventName: "page_view", eventType: "view", pagePath: location.pathname, pageName: currentMenuKey || location.pathname });
  }, [currentMenuKey, isAuthenticated, location.pathname]);

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  if (
    navigationStatus === "ready" &&
    currentMenuKey &&
    !menuItemsHasKey(visibleMenuItems, currentMenuKey)
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
    trackInteraction({ eventName: "sidebar_todo_click", resourceType: "sidebar", resourceId: "todo" });
    navigate(isTodoPage ? todoReturnPath || "/" : "/agent/todos");
  };

  const prepareMenuRoute = (path: string) => {
    if (!path || path === location.pathname) return;
    routeWarmupCancelRef.current();
    preloadRoutePath(path);
    preloadRouteDataPath(path, { tenantId, userId });
  };

  const navigatePreparedMenuRoute = async (event: React.MouseEvent<HTMLAnchorElement>, path: string) => {
    if (
      event.defaultPrevented
      || event.button !== 0
      || event.metaKey
      || event.ctrlKey
      || event.shiftKey
      || event.altKey
    ) return;
    if (path === location.pathname) {
      event.preventDefault();
      routeIntentGenerationRef.current += 1;
      setPendingRoutePath("");
      return;
    }
    event.preventDefault();
    const generation = routeIntentGenerationRef.current + 1;
    routeIntentGenerationRef.current = generation;
    setPendingRoutePath(path);
    prepareMenuRoute(path);
    try {
      await prepareRoutePath(path, { navigationIntent: true });
    } catch {
      // The existing route error boundary remains authoritative for import failures.
    }
    if (routeIntentGenerationRef.current !== generation) return;
    startTransition(() => { void navigate(path); });
  };

  return (
    <div className="flex h-screen bg-white overflow-hidden" data-agent-layout-shell="true">
      {sidebarCollapsed ? (
        <div
          className="fixed bottom-0 left-0 top-0 z-[60] hidden w-10 lg:block"
          data-agent-sidebar-expand-zone="true"
          onMouseEnter={() => {
            setSidebarEdgeVisible(true);
          }}
          onMouseLeave={() => setSidebarEdgeVisible(false)}
        >
          <button
            type="button"
            onClick={() => { trackInteraction({ eventName: "sidebar_expand_click", resourceType: "sidebar" }); setSidebarCollapsed(false); }}
            aria-label="展开左侧菜单"
            title="展开菜单"
            data-agent-sidebar-expand="true"
            className={`fixed left-2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full border border-[#d9d9de] bg-white/95 text-[#636366] shadow-lg shadow-black/10 backdrop-blur transition-all duration-150 hover:bg-[#f2f2f7] hover:text-[#1d1d1f] ${sidebarEdgeVisible ? "scale-100 opacity-100" : "pointer-events-none scale-90 opacity-0"}`}
            style={{ top: "50%" }}
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        </div>
      ) : null}
      {/* Sidebar — macOS-style light */}
      <aside data-agent-sidebar="true" data-collapsed={sidebarCollapsed ? "true" : "false"} className={`hidden lg:flex bg-[#fafbfc] flex-col shrink-0 overflow-hidden transition-[width,border-color] duration-200 ease-out ${sidebarCollapsed ? "lg:w-0" : "lg:w-[216px] border-r border-[#ebebf0]"}`}>
        {!sidebarCollapsed ? <>
        {/* Logo */}
        <div className="px-5 pt-6 pb-4" data-agent-sidebar-header="true">
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
              <button type="button" onClick={() => { trackInteraction({ eventName: "sidebar_collapse_click", resourceType: "sidebar" }); setSidebarCollapsed(true); }} aria-label="收起左侧菜单" title="收起菜单" data-agent-sidebar-collapse="true" className="flex h-[26px] w-[26px] items-center justify-center rounded-md border border-[#e5e5ea] bg-[#fafbfc] text-[#8a8a8e] transition-colors hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"><PanelLeftClose className="h-3.5 w-3.5" /></button>
            </div>
          </div>
          <div className="relative mt-3">
            <button
              type="button"
              onClick={() => { trackInteraction({ eventName: "institution_selector_click", resourceType: "institution", resourceId: selectedInstitution }); setInstitutionOpen((open) => !open); }}
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
                      trackInteraction({ eventName: "institution_select", resourceType: "institution", resourceId: institution, extension: { institution } });
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
                    onClick={() => { trackInteraction({ eventName: "primary_menu_click", resourceType: "menu", resourceId: item.key, extension: { label: item.label } }); toggleMenu(item.label); }}
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
                          onMouseEnter={() => {
                            preloadRoutePath(child.path || "");
                            preloadRouteDataPath(child.path || "", { tenantId, userId });
                          }}
                          onFocus={() => {
                            preloadRoutePath(child.path || "");
                            preloadRouteDataPath(child.path || "", { tenantId, userId });
                          }}
                          onPointerDown={() => {
                            prepareMenuRoute(child.path || "");
                          }}
                          onClick={(event) => {
                            trackInteraction({ eventName: "secondary_menu_click", resourceType: "menu", resourceId: child.key, extension: { label: child.label } });
                            void navigatePreparedMenuRoute(event, child.path || "");
                          }}
                          aria-busy={pendingRoutePath === child.path}
                          className={({ isActive }) =>
                            `flex items-center justify-between gap-2 px-2.5 py-[6px] text-[13px] rounded-md transition-colors ${
                              isActive || pendingRoutePath === child.path
                                ? "text-[#1d1d1f] bg-black/[0.05]"
                                : "text-[#8a8a8e] hover:text-[#3a3a3c] hover:bg-black/[0.03]"
                            }`
                          }
                        >
                          <span className="truncate">{child.label}</span>
                          {pendingRoutePath === child.path && <span className="h-3 w-3 shrink-0 animate-spin rounded-full border border-[#c7c7cc] border-t-[#636366]" aria-hidden="true" data-menu-route-pending="true" />}
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
                onMouseEnter={() => {
                  preloadRoutePath(item.path || "");
                  preloadRouteDataPath(item.path || "", { tenantId, userId });
                }}
                onFocus={() => {
                  preloadRoutePath(item.path || "");
                  preloadRouteDataPath(item.path || "", { tenantId, userId });
                }}
                onPointerDown={() => {
                  prepareMenuRoute(item.path || "");
                }}
                onClick={(event) => {
                  trackInteraction({ eventName: "primary_menu_click", resourceType: "menu", resourceId: item.key, extension: { label: item.label } });
                  void navigatePreparedMenuRoute(event, item.path || "");
                }}
                aria-busy={pendingRoutePath === item.path}
                className={({ isActive }) =>
                  `flex items-center gap-2 px-2.5 py-[7px] text-[13px] rounded-md transition-colors mb-px ${
                    isActive || pendingRoutePath === item.path
                      ? "text-[#1d1d1f] bg-black/[0.05]"
                      : "text-[#8a8a8e] hover:text-[#3a3a3c] hover:bg-black/[0.03]"
                  }`
                }
              >
                <item.icon className="w-[15px] h-[15px] opacity-50" />
                <span className="min-w-0 flex-1 truncate">{item.label}</span>
                {pendingRoutePath === item.path && <span className="h-3 w-3 shrink-0 animate-spin rounded-full border border-[#c7c7cc] border-t-[#636366]" aria-hidden="true" data-menu-route-pending="true" />}
              </NavLink>
            );
          })}
        </nav>

        {!isSmartAnalysisPage && (
          <div className="px-4 pb-3">
            <label className="mb-1.5 block text-[10px] font-medium text-[#8a8a8e]" htmlFor="shared-text-model-selector">当前模型</label>
            <div className="relative">
              <select
                id="shared-text-model-selector"
                aria-label="选择全局文本模型"
                value={selectedTextModelId}
                disabled={!textModelOptions.length}
                onChange={(event) => {
                  const next = textModelOptions.find((option) => option.id === event.target.value);
                  if (!next) return;
                  setSelectedTextModelId(next.id);
                  persistTextModelSelection(tenantId, userId, next);
                  trackInteraction({ eventName: "model_select", resourceType: "model", resourceId: next.id, extension: { label: next.label } });
                }}
                className="h-8 w-full appearance-none rounded-lg border border-[#e5e5ea] bg-white px-2.5 pr-7 text-[11px] text-[#3a3a3c] outline-none transition-colors hover:bg-[#f8f8fa] focus:border-[#8a8a8e] disabled:cursor-not-allowed disabled:bg-[#fafbfc] disabled:text-[#aeaeb2]"
              >
                {textModelOptions.length ? textModelOptions.map((option) => (
                  <option key={option.id} value={option.id}>{option.label}</option>
                )) : <option value="">未配置文本模型</option>}
              </select>
              <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#8a8a8e]" />
            </div>
          </div>
        )}

        {/* User */}
        <div className="px-4 py-3.5 border-t border-[#ebebf0]">
          {passwordOpen && (
            <form
              className="mb-3 space-y-2 rounded-lg border border-[#e5e5ea] bg-[#fafbfc] p-2.5"
              data-account-password-form="true"
              onSubmit={async (event) => {
                event.preventDefault();
                setPasswordNotice("");
                setPasswordSaving(true);
                try {
                  await changeAccountPassword({ currentPassword, newPassword });
                  setCurrentPassword("");
                  setNewPassword("");
                  setPasswordNotice("密码已更新");
                } catch (error) {
                  setPasswordNotice(apiErrorMessage(error, "修改密码失败"));
                } finally {
                  setPasswordSaving(false);
                }
              }}
            >
              <input
                type="password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                placeholder="当前密码"
                autoComplete="current-password"
                className="h-8 w-full rounded-md border border-[#e5e5ea] bg-white px-2 text-[11px] text-[#3a3a3c] outline-none"
              />
              <input
                type="password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                placeholder="新密码，至少 6 位"
                autoComplete="new-password"
                className="h-8 w-full rounded-md border border-[#e5e5ea] bg-white px-2 text-[11px] text-[#3a3a3c] outline-none"
              />
              {passwordNotice && <div className="text-[11px] leading-4 text-[#636366]">{passwordNotice}</div>}
              <button
                type="submit"
                disabled={passwordSaving || !currentPassword || !newPassword}
                className="h-7 w-full rounded-md bg-[#1d1d1f] text-[11px] text-white disabled:opacity-40"
              >
                {passwordSaving ? "保存中" : "保存新密码"}
              </button>
            </form>
          )}
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
              onClick={() => {
                setPasswordOpen((open) => !open);
                setPasswordNotice("");
              }}
              className="rounded-md p-1.5 text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"
              aria-label="修改密码"
              title="修改密码"
              data-account-password-toggle="true"
            >
              <KeyRound className="h-3.5 w-3.5" />
            </button>
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
          <div className="flex min-h-full items-center justify-center p-7" data-navigation-loading="true">
            <div className="text-center">
              <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-[#d7e6dd] border-t-[#178a53]" />
              <div className="mt-3 text-[13px] text-[#8a8a8e]">正在加载页面权限…</div>
            </div>
          </div>
        ) : navigationStatus === "failed" ? (
          <div className="m-7 rounded-xl border border-[#ffd7d7] bg-[#fff5f5] px-4 py-3 text-[13px] text-[#b42318]">
            页面权限加载失败，请确认登录状态后刷新页面。
            <button
              type="button"
              className="ml-3 rounded-md border border-[#f5c2c2] bg-white px-2 py-1 text-[12px] text-[#b42318]"
              onClick={() => {
                setNavigationStatus("loading");
                void fetchNavigation({ tenantId, userId }).then((response) => {
                  setAllowedMenuKeys(new Set(Array.isArray(response.menu_keys) ? response.menu_keys : []));
                  setNavigationStatus("ready");
                }).catch(() => setNavigationStatus("failed"));
              }}
            >
              重试
            </button>
          </div>
        ) : (
          <Outlet key={tenantId} />
        )}
      </main>

      <GlobalMessageBoardShortcut />
      <GlobalContextRail />

      <AgentSupervisor />
    </div>
  );
}

const navigationCachePrefix = "sda-navigation-keys-v1";

function allMenuKeys(items: MenuItem[]): string[] {
  return items.flatMap((item) => [item.key, ...(item.children?.map((child) => child.key) || [])]);
}

function navigationCacheKey(userId: string, tenantId: string) {
  return `${navigationCachePrefix}:${userId}:${tenantId}`;
}

function readCachedNavigation(userId: string, tenantId: string): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.sessionStorage.getItem(navigationCacheKey(userId, tenantId));
    const parsed = raw ? JSON.parse(raw) as unknown : [];
    return Array.isArray(parsed) ? parsed.filter((key): key is string => typeof key === "string" && Boolean(key)) : [];
  } catch {
    return [];
  }
}

function writeCachedNavigation(userId: string, tenantId: string, keys: string[]) {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(navigationCacheKey(userId, tenantId), JSON.stringify(keys));
  } catch {
    // Private mode or quota errors must not block login.
  }
}

function filterMenuItems(items: MenuItem[], allowedKeys: Set<string> | null, institutionCount: number): MenuItem[] {
  if (!allowedKeys) return items;
  const filtered = items
    .map((item) => {
      const children = item.children?.filter((child) => allowedKeys.has(child.key));
      if (!allowedKeys.has(item.key) && !children?.length) return null;
      return children ? { ...item, children } : item;
    })
    .filter((item): item is MenuItem => item !== null);
  if (institutionCount < 2) return filtered.filter((item) => item.key !== "dashboard");
  if (filtered.some((item) => item.key === "dashboard")) return filtered;
  const dashboard = items.find((item) => item.key === "dashboard");
  return dashboard ? [dashboard, ...filtered] : filtered;
}

function menuItemsHasKey(items: MenuItem[], key: string) {
  return items.some((item) => item.key === key || item.children?.some((child) => child.key === key));
}

function firstVisibleMenuPath(items: MenuItem[]): string | null {
  for (const item of items) {
    if (item.path) return item.path;
    const child = item.children?.find((candidate) => candidate.path);
    if (child?.path) return child.path;
  }
  return null;
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
