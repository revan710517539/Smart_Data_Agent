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
  workspace: () => import("./components/DataAgentWorkspace"),
  assets: () => import("./components/DataAssets"),
  notifications: () => import("./components/Notifications"),
  settings: () => import("./components/SystemSettings"),
  login: () => import("./components/LoginPage"),
  skills: () => import("./components/SkillPluginManager"),
  tools: () => import("./components/ExternalToolManager"),
  analysisConfig: () => import("./components/AnalysisConfigManager"),
};

export const routePreloaders: Array<{ test: (path: string) => boolean; loader: () => Promise<unknown> }> = [
  { test: (path) => path.startsWith("/self-analysis/query") || path.startsWith("/self-analysis/reports"), loader: routeLoaders.analysis },
  { test: (path) => path.startsWith("/self-analysis/config"), loader: routeLoaders.analysisConfig },
  { test: (path) => path.startsWith("/agent/tasks") || path.startsWith("/agent/todos"), loader: routeLoaders.workspace },
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

export function preloadRoutePath(path: string) {
  const loader = routePreloaders.find((candidate) => candidate.test(path))?.loader;
  if (loader) void loader();
}
