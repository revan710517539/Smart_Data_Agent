const routeLoaders = {
  dashboard: () => import("./components/Dashboard"),
  funnel: () => import("./components/BusinessFunnel"),
  sandbox: () => import("./components/BusinessSandbox"),
  supervision: () => import("./components/InstitutionSupervision"),
  weekly: () => import("./components/WeeklyReport"),
  email: () => import("./components/EmailDailyReport"),
  customers: () => import("./components/CustomerInsight"),
  competition: () => import("./components/CompetitionAnalysis"),
  analysis: () => import("./components/SelfAnalysis"),
  visualReports: () => import("./components/VisualReportBuilder"),
  workspace: () => import("./components/DataAgentWorkspace"),
  assets: () => import("./components/DataAssets"),
  notifications: () => import("./components/Notifications"),
  settings: () => import("./components/SystemSettings"),
  login: () => import("./components/LoginPage"),
  skills: () => import("./components/SkillPluginManager"),
  tools: () => import("./components/ExternalToolManager"),
  analysisConfig: () => import("./components/AnalysisConfigManager"),
  messageBoard: () => import("./components/MessageBoardManagement"),
};

export const routePreloaders: Array<{ test: (path: string) => boolean; loader: () => Promise<unknown> }> = [
  { test: (path) => path === "/dashboard", loader: routeLoaders.dashboard },
  { test: (path) => path.startsWith("/self-analysis/visual-reports"), loader: routeLoaders.visualReports },
  { test: (path) => path.startsWith("/self-analysis/query") || path.startsWith("/self-analysis/reports"), loader: routeLoaders.analysis },
  { test: (path) => path.startsWith("/self-analysis/config"), loader: routeLoaders.analysisConfig },
  { test: (path) => path.startsWith("/agent/tasks") || path.startsWith("/agent/todos"), loader: routeLoaders.workspace },
  { test: (path) => path.startsWith("/agent/message-board"), loader: routeLoaders.messageBoard },
  { test: (path) => path.startsWith("/agent/skills"), loader: routeLoaders.skills },
  { test: (path) => path.startsWith("/data-assets/tools"), loader: routeLoaders.tools },
  { test: (path) => path.startsWith("/data-assets/"), loader: routeLoaders.assets },
  { test: (path) => path.startsWith("/settings/"), loader: routeLoaders.settings },
  { test: (path) => path.startsWith("/weekly-report"), loader: routeLoaders.weekly },
  { test: (path) => path.startsWith("/supervision"), loader: routeLoaders.supervision },
  { test: (path) => path.startsWith("/customers"), loader: routeLoaders.customers },
  { test: (path) => path.startsWith("/competition"), loader: routeLoaders.competition },
  { test: (path) => path.startsWith("/notifications/"), loader: routeLoaders.notifications },
];

const routeLoaderPromises = new Map<() => Promise<unknown>, Promise<unknown>>();

export function preloadRoutePath(path: string) {
  const loader = resolveRouteLoader(path);
  if (loader) void preloadRouteLoader(loader).catch(() => undefined);
}

export function warmVisibleRoutePaths(paths: string[], currentPath: string) {
  const currentGroup = routeWarmGroup(currentPath);
  const pendingLoaders = Array.from(new Set(
    paths
      .filter((path) => path && path !== currentPath)
      .map((path, index) => ({ path, index }))
      .sort((left, right) => {
        const leftIsNearby = routeWarmGroup(left.path) === currentGroup;
        const rightIsNearby = routeWarmGroup(right.path) === currentGroup;
        return Number(rightIsNearby) - Number(leftIsNearby) || left.index - right.index;
      })
      .map(({ path }) => path)
      .map(resolveRouteLoader)
      .filter((loader): loader is () => Promise<unknown> => Boolean(loader)),
  ));
  let cancelled = false;
  let idleId: number | null = null;
  let timeoutId: number | null = null;

  const scheduleNext = () => {
    if (cancelled || !pendingLoaders.length) return;
    if (typeof window.requestIdleCallback === "function") {
      idleId = window.requestIdleCallback(runNext, { timeout: 800 });
      return;
    }
    timeoutId = window.setTimeout(runNext, 180);
  };

  const runNext = () => {
    idleId = null;
    timeoutId = null;
    if (cancelled) return;
    const loader = pendingLoaders.shift();
    if (!loader) return;
    void preloadRouteLoader(loader).catch(() => undefined).finally(scheduleNext);
  };

  scheduleNext();
  return () => {
    cancelled = true;
    if (idleId !== null && typeof window.cancelIdleCallback === "function") window.cancelIdleCallback(idleId);
    if (timeoutId !== null) window.clearTimeout(timeoutId);
  };
}

function routeWarmGroup(path: string) {
  if (path.startsWith("/self-analysis/")) return "self-analysis";
  if (path.startsWith("/weekly-report") || path.startsWith("/supervision")) return "business-analysis";
  if (path.startsWith("/agent/")) return "agent";
  if (path.startsWith("/data-assets/")) return "data-assets";
  if (path.startsWith("/notifications/")) return "notifications";
  if (path.startsWith("/settings/")) return "settings";
  return path.split("/").filter(Boolean)[0] || "root";
}

function resolveRouteLoader(path: string) {
  return routePreloaders.find((candidate) => candidate.test(path))?.loader;
}

function preloadRouteLoader(loader: () => Promise<unknown>) {
  const existing = routeLoaderPromises.get(loader);
  if (existing) return existing;
  const pending = loader().catch((error) => {
    routeLoaderPromises.delete(loader);
    throw error;
  });
  routeLoaderPromises.set(loader, pending);
  return pending;
}
