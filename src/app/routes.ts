import { createElement, lazy, Suspense, type ComponentType } from "react";
import { createBrowserRouter, Navigate } from "react-router";
import { Layout } from "./components/Layout";
import { PlaceholderPage } from "./components/PlaceholderPage";
import { RouteErrorPage } from "./components/RouteErrorPage";

const Dashboard = lazyNamed(() => import("./components/Dashboard"), "Dashboard");
const BusinessFunnel = lazyNamed(() => import("./components/BusinessFunnel"), "BusinessFunnel");
const BusinessSandbox = lazyNamed(() => import("./components/BusinessSandbox"), "BusinessSandbox");
const InstitutionSupervision = lazyNamed(() => import("./components/InstitutionSupervision"), "InstitutionSupervision");
const WeeklyReport = lazyNamed(() => import("./components/WeeklyReport"), "WeeklyReport");
const EmailDailyReport = lazyNamed(() => import("./components/EmailDailyReport"), "EmailDailyReport");
const CustomerInsight = lazyNamed(() => import("./components/CustomerInsight"), "CustomerInsight");
const CompetitionAnalysis = lazyNamed(() => import("./components/CompetitionAnalysis"), "CompetitionAnalysis");
const SelfAnalysis = lazyNamed(() => import("./components/SelfAnalysis"), "SelfAnalysis");
const DataAgentWorkspace = lazyNamed(() => import("./components/DataAgentWorkspace"), "DataAgentWorkspace");
const DataAssets = lazyNamed(() => import("./components/DataAssets"), "DataAssets");
const Notifications = lazyNamed(() => import("./components/Notifications"), "Notifications");
const SystemSettings = lazyNamed(() => import("./components/SystemSettings"), "SystemSettings");
const LoginPage = lazyNamed(() => import("./components/LoginPage"), "LoginPage");
const SkillPluginManager = lazyNamed(() => import("./components/SkillPluginManager"), "SkillPluginManager");
const ExternalToolManager = lazyNamed(() => import("./components/ExternalToolManager"), "ExternalToolManager");
const AnalysisConfigManager = lazyNamed(() => import("./components/AnalysisConfigManager"), "AnalysisConfigManager");

function lazyNamed(loader: () => Promise<Record<string, unknown>>, exportName: string) {
  return lazy(async () => {
    try {
      const module = await loader();
      clearRouteImportRetry();
      return { default: module[exportName] as ComponentType };
    } catch (error) {
      if (isDynamicImportError(error) && await canSafelyReloadRouteImport()) {
        window.location.reload();
        return await new Promise<{ default: ComponentType }>(() => undefined);
      }
      throw error;
    }
  });
}

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
  return createElement("div", { className: "p-7 text-[13px] text-[#8a8a8e]" }, "页面加载中...");
}

export const router = createBrowserRouter([
  { path: "/login", Component: withPageSuspense(LoginPage), errorElement: createElement(RouteErrorPage) },
  {
    path: "/",
    Component: Layout,
    errorElement: createElement(RouteErrorPage),
    children: [
      { index: true, Component: withPageSuspense(Dashboard) },
      { path: "funnel", Component: withPageSuspense(BusinessFunnel) },
      { path: "sandbox", Component: withPageSuspense(BusinessSandbox) },
      { path: "supervision", Component: withPageSuspense(InstitutionSupervision) },
      { path: "weekly-report", Component: withPageSuspense(WeeklyReport) },
      { path: "email-daily", Component: withPageSuspense(EmailDailyReport) },
      { path: "customers", Component: withPageSuspense(CustomerInsight) },
      { path: "single-customer", Component: () => createElement(Navigate, { to: "/customers", replace: true }) },
      { path: "competition", Component: withPageSuspense(CompetitionAnalysis) },
      { path: "self-analysis", Component: () => createElement(Navigate, { to: "/self-analysis/query", replace: true }) },
      { path: "self-analysis/query", Component: withPageSuspense(SelfAnalysis) },
      { path: "self-analysis/reports", Component: withPageSuspense(SelfAnalysis) },
      { path: "self-analysis/config", Component: withPageSuspense(AnalysisConfigManager) },
      { path: "agent", Component: () => createElement(Navigate, { to: "/agent/tasks", replace: true }) },
      { path: "agent/todos", Component: withPageSuspense(DataAgentWorkspace) },
      { path: "agent/tasks", Component: withPageSuspense(DataAgentWorkspace) },
      { path: "agent/insights", Component: () => createElement(Navigate, { to: "/agent/tasks", replace: true }) },
      { path: "agent/abilities", Component: withPageSuspense(DataAgentWorkspace) },
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
      {
        path: "*",
        Component: () => PlaceholderPage({ title: "页面不存在" }),
      },
    ],
  },
]);
