export type RouteModule = Record<string, unknown>;
export type RouteLoader = () => Promise<RouteModule>;

export const routeLoaders = {
  dashboard: () => import("./components/Dashboard"),
  funnel: () => import("./components/BusinessFunnel"),
  sandbox: () => import("./components/BusinessSandbox"),
  supervision: () => import("./components/InstitutionSupervision"),
  customerSegment: () => import("./components/CustomerSegmentAnalysis"),
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
  skins: () => import("./components/SkinManagement"),
  login: () => import("./components/LoginPage"),
  layout: () => import("./components/Layout"),
  skills: () => import("./components/SkillPluginManager"),
  tools: () => import("./components/ExternalToolManager"),
  analysisConfig: () => import("./components/AnalysisConfigManager"),
  messageBoard: () => import("./components/MessageBoardManagement"),
  interactionAnalytics: () => import("./components/InteractionAnalytics"),
  bridge: () => import("./components/BridgeAuthorization"),
};

export const routePreloaders: Array<{ test: (path: string) => boolean; loader: RouteLoader }> = [
  { test: (path) => path === "/dashboard", loader: routeLoaders.dashboard },
  { test: (path) => path === "/funnel", loader: routeLoaders.funnel },
  { test: (path) => path === "/sandbox", loader: routeLoaders.sandbox },
  { test: (path) => path.startsWith("/self-analysis/visual-reports"), loader: routeLoaders.visualReports },
  { test: (path) => path.startsWith("/self-analysis/query") || path.startsWith("/self-analysis/reports"), loader: routeLoaders.analysis },
  { test: (path) => path.startsWith("/self-analysis/config"), loader: routeLoaders.analysisConfig },
  { test: (path) => path.startsWith("/agent/tasks") || path.startsWith("/agent/todos"), loader: routeLoaders.workspace },
  { test: (path) => path.startsWith("/agent/message-board"), loader: routeLoaders.messageBoard },
  { test: (path) => path.startsWith("/agent/interaction-analytics"), loader: routeLoaders.interactionAnalytics },
  { test: (path) => path.startsWith("/agent/skills"), loader: routeLoaders.skills },
  { test: (path) => path.startsWith("/data-assets/tools"), loader: routeLoaders.tools },
  { test: (path) => path.startsWith("/data-assets/"), loader: routeLoaders.assets },
  { test: (path) => path.startsWith("/settings/skin"), loader: routeLoaders.skins },
  { test: (path) => path.startsWith("/settings/"), loader: routeLoaders.settings },
  { test: (path) => path.startsWith("/weekly-report"), loader: routeLoaders.weekly },
  { test: (path) => path.startsWith("/email-daily"), loader: routeLoaders.email },
  { test: (path) => path.startsWith("/supervision"), loader: routeLoaders.supervision },
  { test: (path) => path.startsWith("/customer-segment-analysis"), loader: routeLoaders.customerSegment },
  { test: (path) => path.startsWith("/customers"), loader: routeLoaders.customers },
  { test: (path) => path.startsWith("/competition"), loader: routeLoaders.competition },
  { test: (path) => path.startsWith("/notifications/"), loader: routeLoaders.notifications },
  { test: (path) => path.startsWith("/bridge-authorize"), loader: routeLoaders.bridge },
];

const routeLoaderPromises = new Map<RouteLoader, Promise<RouteModule>>();
const preparedRouteModules = new Map<RouteLoader, RouteModule>();
const preparedNavigationFailures = new WeakSet<RouteLoader>();

export function preloadRoutePath(path: string) {
  void prepareRoutePath(path).catch(() => undefined);
}

export function prepareRoutePath(path: string, options: { navigationIntent?: boolean } = {}): Promise<unknown> {
  const loader = resolveRouteLoader(path);
  if (!loader) return Promise.resolve();
  const pending = prepareRouteLoader(loader);
  if (!options.navigationIntent) return pending;
  return pending.then((module) => {
    preparedNavigationFailures.delete(loader);
    return module;
  }).catch((error) => {
    preparedNavigationFailures.add(loader);
    throw error;
  });
}

export function consumePreparedNavigationFailure(loader: RouteLoader) {
  const failed = preparedNavigationFailures.has(loader);
  preparedNavigationFailures.delete(loader);
  return failed;
}

export function readPreparedRouteModule(loader: RouteLoader) {
  return preparedRouteModules.get(loader) || null;
}

export function prepareRouteLoader(loader: RouteLoader): Promise<RouteModule> {
  const prepared = preparedRouteModules.get(loader);
  if (prepared) return Promise.resolve(prepared);
  const existing = routeLoaderPromises.get(loader);
  if (existing) return existing;
  const pending = loader()
    .then((module) => {
      preparedRouteModules.set(loader, module);
      return module;
    })
    .catch((error) => {
      routeLoaderPromises.delete(loader);
      throw error;
    });
  routeLoaderPromises.set(loader, pending);
  return pending;
}

export function warmVisibleRoutePaths(paths: string[], currentPath: string) {
  const currentGroup = routeWarmGroup(currentPath);
  const nearbyLoaders = new Set<RouteLoader>();
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
      .map((path) => {
        const loader = resolveRouteLoader(path);
        if (loader && routeWarmGroup(path) === currentGroup) nearbyLoaders.add(loader);
        return loader;
      })
      .filter((loader): loader is RouteLoader => Boolean(loader)),
  ));
  let cancelled = false;
  let idleId: number | null = null;
  let timeoutId: number | null = null;
  let crossGroupDelayComplete = false;

  const scheduleNext = () => {
    if (cancelled || !pendingLoaders.length) return;
    if (!crossGroupDelayComplete && !nearbyLoaders.has(pendingLoaders[0])) {
      crossGroupDelayComplete = true;
      timeoutId = window.setTimeout(scheduleNext, 1_200);
      return;
    }
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
    void prepareRouteLoader(loader).catch(() => undefined).finally(scheduleNext);
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
