import { createElement, Suspense, type ComponentType } from "react";
import { createBrowserRouter, Navigate } from "react-router";
import { PlaceholderPage } from "./components/PlaceholderPage";
import { RouteErrorPage } from "./components/RouteErrorPage";
import { consumePreparedNavigationFailure, prepareRouteLoader, readPreparedRouteModule, routeLoaders, routePreloaders, type RouteLoader } from "./routePreload";

const Dashboard = preparedNamed(routeLoaders.dashboard, "Dashboard");
const BusinessFunnel = preparedNamed(routeLoaders.funnel, "BusinessFunnel");
const BusinessSandbox = preparedNamed(routeLoaders.sandbox, "BusinessSandbox");
const InstitutionSupervision = preparedNamed(routeLoaders.supervision, "InstitutionSupervision");
const CustomerSegmentAnalysis = preparedNamed(routeLoaders.customerSegment, "CustomerSegmentAnalysis");
const WeeklyReport = preparedNamed(routeLoaders.weekly, "WeeklyReport");
const EmailDailyReport = preparedNamed(routeLoaders.email, "EmailDailyReport");
const CustomerInsight = preparedNamed(routeLoaders.customers, "CustomerInsight");
const CompetitionAnalysis = preparedNamed(routeLoaders.competition, "CompetitionAnalysis");
const SelfAnalysis = preparedNamed(routeLoaders.analysis, "SelfAnalysis");
const VisualReportBuilder = preparedNamed(routeLoaders.visualReports, "VisualReportBuilder");
const DataAgentWorkspace = preparedNamed(routeLoaders.workspace, "DataAgentWorkspace");
const DataAssets = preparedNamed(routeLoaders.assets, "DataAssets");
const Notifications = preparedNamed(routeLoaders.notifications, "Notifications");
const SystemSettings = preparedNamed(routeLoaders.settings, "SystemSettings");
const SkinManagement = preparedNamed(routeLoaders.skins, "SkinManagement");
const LoginPage = preparedNamed(routeLoaders.login, "LoginPage");
const Layout = preparedNamed(routeLoaders.layout, "Layout", false);
const SkillPluginManager = preparedNamed(routeLoaders.skills, "SkillPluginManager");
const ExternalToolManager = preparedNamed(routeLoaders.tools, "ExternalToolManager");
const AnalysisConfigManager = preparedNamed(routeLoaders.analysisConfig, "AnalysisConfigManager");
const BridgeAuthorization = preparedNamed(routeLoaders.bridge, "BridgeAuthorization");
const MessageBoardManagement = preparedNamed(routeLoaders.messageBoard, "MessageBoardManagement");
const InteractionAnalytics = preparedNamed(routeLoaders.interactionAnalytics, "InteractionAnalytics");

/* Menu navigation fills this shared module cache before changing location.
 * Direct URLs still suspend here and retain the established recovery path. */
function preparedNamed(loader: RouteLoader, exportName: string, clearRetryOnSuccess = true) {
  let guardedPromise: Promise<RouteModuleResult> | null = null;
  let terminalError: unknown = null;
  const prepare = () => {
    const ready = readPreparedRouteModule(loader);
    if (ready) return Promise.resolve(ready);
    if (guardedPromise) return guardedPromise;
    guardedPromise = prepareRouteLoader(loader).then((module) => {
      terminalError = null;
      if (clearRetryOnSuccess) clearRouteImportRetry();
      return module;
    }).catch(async (error) => {
      guardedPromise = null;
      const failedPreparedNavigation = consumePreparedNavigationFailure(loader);
      if (!failedPreparedNavigation && isDynamicImportError(error) && await canSafelyReloadRouteImport()) {
        window.location.reload();
        return await new Promise<RouteModuleResult>(() => undefined);
      }
      terminalError = error;
      throw error;
    });
    return guardedPromise;
  };
  return function PreparedRoute() {
    if (terminalError) throw terminalError;
    const module = readPreparedRouteModule(loader);
    if (!module) throw prepare();
    if (clearRetryOnSuccess) clearRouteImportRetry();
    return createElement(module[exportName] as ComponentType);
  };
}

type RouteModuleResult = Record<string, unknown>;

const routeImportRetryKey = "smart-data-agent:route-import-retry";

function isDynamicImportError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error || "");
  return /dynamically imported module|importing a module script failed|error loading dynamically imported module/i.test(message);
}

async function canSafelyReloadRouteImport() {
  const lastRetry = Number(window.sessionStorage.getItem(routeImportRetryKey) || 0);
  if (Date.now() - lastRetry < 30_000) return false;
  try {
    const response = await fetch("/", { method: "HEAD", cache: "no-store" });
    if (!response.ok) return false;
    window.sessionStorage.setItem(routeImportRetryKey, String(Date.now()));
    return true;
  } catch {
    return false;
  }
}

function clearRouteImportRetry() {
  window.sessionStorage.removeItem(routeImportRetryKey);
}

function withPageSuspense(Component: ComponentType) {
  return function SuspendedRoute() {
    return createElement(
      Suspense,
      { fallback: createElement(RouteFallback) },
      createElement(Component),
    );
  };
}

function RouteFallback() {
  return createElement(
    "div",
    { className: "p-7", "aria-label": "页面内容加载中" },
    createElement("div", { className: "inline-flex h-7 items-center gap-2 text-[12px] text-[#8a8a8e]", "data-route-fallback-indicator": "compact" },
      createElement("span", { className: "h-3.5 w-3.5 animate-spin rounded-full border border-[#d1d1d6] border-t-[#636366]", "aria-hidden": "true" }),
      createElement("span", null, "正在准备页面"),
    ),
    createElement("div", { className: "mt-5 grid animate-pulse gap-4 md:grid-cols-3" },
      ...Array.from({ length: 3 }, (_, index) => createElement("div", { key: index, className: "h-28 rounded-xl border border-[#f0f0f2] bg-[#fafbfc]" })),
    ),
    createElement("div", { className: "mt-5 h-72 animate-pulse rounded-xl border border-[#f0f0f2] bg-[#fafbfc]" }),
  );
}

export const router = createBrowserRouter([
  { path: "/login", Component: withPageSuspense(LoginPage), errorElement: createElement(RouteErrorPage) },
  {
    path: "/",
    Component: withPageSuspense(Layout),
    errorElement: createElement(RouteErrorPage),
    children: [
      { index: true, Component: () => createElement(Navigate, { to: "/self-analysis/query", replace: true }) },
      { path: "dashboard", Component: withPageSuspense(Dashboard) },
      { path: "funnel", Component: withPageSuspense(BusinessFunnel) },
      { path: "sandbox", Component: withPageSuspense(BusinessSandbox) },
      { path: "supervision", Component: withPageSuspense(InstitutionSupervision) },
      { path: "customer-segment-analysis", Component: withPageSuspense(CustomerSegmentAnalysis) },
      { path: "weekly-report", Component: withPageSuspense(WeeklyReport) },
      { path: "email-daily", Component: withPageSuspense(EmailDailyReport) },
      { path: "customers", Component: withPageSuspense(CustomerInsight) },
      { path: "single-customer", Component: () => createElement(Navigate, { to: "/customers", replace: true }) },
      { path: "competition", Component: withPageSuspense(CompetitionAnalysis) },
      { path: "self-analysis", Component: () => createElement(Navigate, { to: "/self-analysis/query", replace: true }) },
      { path: "self-analysis/visual-reports", Component: withPageSuspense(VisualReportBuilder) },
      { path: "self-analysis/query", Component: withPageSuspense(SelfAnalysis) },
      { path: "self-analysis/reports", Component: withPageSuspense(SelfAnalysis) },
      { path: "self-analysis/config", Component: withPageSuspense(AnalysisConfigManager) },
      { path: "agent", Component: () => createElement(Navigate, { to: "/agent/tasks", replace: true }) },
      { path: "agent/todos", Component: withPageSuspense(DataAgentWorkspace) },
      { path: "agent/tasks", Component: withPageSuspense(DataAgentWorkspace) },
      { path: "agent/message-board", Component: withPageSuspense(MessageBoardManagement) },
      { path: "agent/interaction-analytics", Component: withPageSuspense(InteractionAnalytics) },
      { path: "agent/insights", Component: () => createElement(Navigate, { to: "/agent/tasks", replace: true }) },
      { path: "agent/abilities", Component: () => createElement(Navigate, { to: "/agent/tasks", replace: true }) },
      { path: "agent/skills", Component: withPageSuspense(SkillPluginManager) },
      { path: "data-assets", Component: () => createElement(Navigate, { to: "/data-assets/metrics", replace: true }) },
      { path: "data-assets/metrics", Component: withPageSuspense(DataAssets) },
      { path: "data-assets/knowledge", Component: withPageSuspense(DataAssets) },
      { path: "data-assets/behavior", Component: () => createElement(Navigate, { to: "/data-assets/knowledge", replace: true }) },
      { path: "data-assets/data-management", Component: withPageSuspense(DataAssets) },
      { path: "data-assets/quality", Component: withPageSuspense(DataAssets) },
      { path: "data-assets/tools", Component: withPageSuspense(ExternalToolManager) },
      { path: "notifications", Component: () => createElement(Navigate, { to: "/notifications/alerts", replace: true }) },
      { path: "notifications/alerts", Component: withPageSuspense(Notifications) },
      { path: "notifications/subscriptions", Component: withPageSuspense(Notifications) },
      { path: "notifications/history", Component: withPageSuspense(Notifications) },
      { path: "settings", Component: () => createElement(Navigate, { to: "/settings/users", replace: true }) },
      { path: "settings/users", Component: withPageSuspense(SystemSettings) },
      { path: "settings/roles", Component: withPageSuspense(SystemSettings) },
      { path: "settings/audit", Component: withPageSuspense(SystemSettings) },
      { path: "settings/config", Component: withPageSuspense(SystemSettings) },
      { path: "settings/skin", Component: withPageSuspense(SkinManagement) },
      { path: "bridge-authorize", Component: withPageSuspense(BridgeAuthorization) },
      {
        path: "*",
        Component: () => PlaceholderPage({ title: "页面不存在" }),
      },
    ],
  },
]);
