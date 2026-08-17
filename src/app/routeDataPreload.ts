import { fetchApplicationModule, type ApplicationModuleKey } from "./services/applicationApi";
import { fetchAccessRolePolicies, fetchAccessUsers } from "./services/accessControlApi";
import { fetchAuditLogs } from "./services/auditApi";
import { fetchAutomationWorkspace } from "./services/automationApi";
import { fetchPlatformCapabilities } from "./services/capabilitiesApi";
import { fetchDataAssets } from "./services/dataAssetApi";
import { fetchMetricDictionary } from "./services/metricDictionaryApi";
import { fetchSavedAnalysisResults } from "./services/reportApi";
import { fetchSystemConfig } from "./services/systemConfigApi";
import { fetchVisualReports } from "./services/visualReportApi";

type RouteDataContext = { tenantId: string; userId: string };

/**
 * Warms only the data required by the route the user is pointing at. Service
 * caches coalesce this request with the route mount and keep tenant APIs
 * HTTP no-store, so preloading cannot cross tenant or user boundaries.
 */
export function preloadRouteDataPath(path: string, context: RouteDataContext) {
  const tasks = routeDataTasks(path, context);
  if (!tasks.length) return;
  void Promise.allSettled(tasks);
}

function routeDataTasks(path: string, { tenantId, userId }: RouteDataContext): Array<Promise<unknown>> {
  if (path.startsWith("/self-analysis/config")) {
    return [
      fetchDataAssets({ tenantId, userId }),
      fetchDataAssets({ tenantId, userId, scope: "knowledge" }),
    ];
  }
  if (path.startsWith("/self-analysis/visual-reports")) {
    return [
      fetchVisualReports({ tenantId, userId }),
      fetchDataAssets({ tenantId, userId, scope: "visualization" }),
    ];
  }
  if (path.startsWith("/self-analysis/reports")) {
    return [
      fetchSavedAnalysisResults({ tenantId, userId }),
      fetchVisualReports({ tenantId, userId }),
    ];
  }
  if (path.startsWith("/self-analysis/query")) {
    return [
      fetchSavedAnalysisResults({ tenantId, userId }),
      fetchDataAssets({ tenantId, userId }),
      fetchDataAssets({ tenantId, userId, scope: "runtime" }),
      fetchMetricDictionary({ tenantId, userId }),
    ];
  }
  if (path.startsWith("/agent/skills")) {
    return [fetchDataAssets({ tenantId, userId, scope: "knowledge" })];
  }
  if (path.startsWith("/agent/tasks")) {
    return [
      fetchAutomationWorkspace({ tenantId, userId }),
      fetchPlatformCapabilities({ tenantId, userId }),
      fetchDataAssets({ tenantId, userId }),
      fetchMetricDictionary({ tenantId, userId }),
      fetchSystemConfig({ tenantId, userId }),
    ];
  }
  if (path.startsWith("/data-assets/tools")) {
    return [fetchDataAssets({ tenantId, userId })];
  }
  if (path.startsWith("/data-assets/")) {
    return [fetchDataAssets({ tenantId, userId }), fetchMetricDictionary({ tenantId, userId })];
  }
  if (path.startsWith("/settings/config")) {
    return [fetchSystemConfig({ tenantId, userId })];
  }
  if (path.startsWith("/settings/users") || path.startsWith("/settings/roles")) {
    return [fetchAccessUsers({ tenantId }), fetchAccessRolePolicies({ tenantId })];
  }
  if (path.startsWith("/settings/audit")) {
    return [fetchAuditLogs({ tenantId })];
  }

  const moduleKey = applicationModuleForPath(path);
  return moduleKey ? [fetchApplicationModule({ tenantId, userId, moduleKey })] : [];
}

function applicationModuleForPath(path: string): ApplicationModuleKey | null {
  if (path === "/dashboard") return "dashboard";
  if (path.startsWith("/weekly-report")) return "weekly_report";
  if (path.startsWith("/supervision")) return "institution_supervision";
  if (path.startsWith("/customers")) return "customer_insight";
  if (path.startsWith("/competition")) return "competition_analysis";
  if (path.startsWith("/agent/todos")) return "agent_workspace";
  if (path.startsWith("/notifications/")) return "notifications";
  return null;
}
