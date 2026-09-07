import { fetchApplicationModule, type ApplicationModuleKey } from "./services/applicationApi";
import { fetchAccessRolePolicies, fetchAccessUsers } from "./services/accessControlApi";
import { defaultAuditSince, fetchAuditLogs } from "./services/auditApi";
import { fetchAutomationWorkspace } from "./services/automationApi";
import { fetchPlatformCapabilities } from "./services/capabilitiesApi";
import { fetchDataAssets, fetchPageDataWorkspace } from "./services/dataAssetApi";
import { fetchMessageBoardAdmin } from "./services/messageBoardApi";
import { fetchInteractionAnalytics } from "./services/interactionAnalyticsApi";
import { fetchMetricDictionary } from "./services/metricDictionaryApi";
import { fetchSavedAnalysisResults } from "./services/reportApi";
import { fetchAnalysisRuntimeConfig, fetchSystemConfig } from "./services/systemConfigApi";
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
      fetchAnalysisRuntimeConfig({ tenantId, userId, speechApplicationModule: "realtime_voice_input" }),
    ];
  }
  if (path.startsWith("/agent/skills")) {
    return [fetchDataAssets({ tenantId, userId, scope: "knowledge" })];
  }
  if (path.startsWith("/agent/tasks")) {
    return [
      fetchAutomationWorkspace({ tenantId, userId }),
      fetchPlatformCapabilities({ tenantId, userId }),
    ];
  }
  if (path.startsWith("/agent/message-board")) {
    return [fetchMessageBoardAdmin({ page: 1, pageSize: 20 }, { tenantId, userId })];
  }
  if (path.startsWith("/agent/interaction-analytics")) {
    return [fetchInteractionAnalytics({ days: 30, page: 1, pageSize: 50 }, { tenantId, userId })];
  }
  if (path.startsWith("/data-assets/tools")) {
    return [fetchDataAssets({ tenantId, userId })];
  }
  if (path.startsWith("/data-assets/metrics")) {
    return [fetchMetricDictionary({ tenantId, userId })];
  }
  if (path.startsWith("/data-assets/knowledge")) {
    return [fetchDataAssets({ tenantId, userId, scope: "knowledge" })];
  }
  if (path.startsWith("/data-assets/rules")) {
    return [fetchDataAssets({ tenantId, userId })];
  }
  if (path.startsWith("/data-assets/quality")) {
    return [];
  }
  if (path.startsWith("/data-assets/")) {
    return [fetchDataAssets({ tenantId, userId })];
  }
  if (path.startsWith("/settings/config")) {
    return [fetchSystemConfig({ tenantId, userId })];
  }
  if (path.startsWith("/settings/users") || path.startsWith("/settings/roles")) {
    return [fetchAccessUsers({ tenantId }), fetchAccessRolePolicies({ tenantId })];
  }
  if (path.startsWith("/settings/audit")) {
    return [fetchAuditLogs({ tenantId, since: defaultAuditSince() })];
  }

  if (path === "/dashboard") {
    return [fetchPageDataWorkspace({ tenantId, userId, pageCode: "dashboard" })];
  }
  if (path.startsWith("/weekly-report")) {
    return [
      fetchPageDataWorkspace({ tenantId, userId, pageCode: "weekly_report" }),
      fetchVisualReports({ tenantId, userId }),
    ];
  }
  if (path.startsWith("/supervision")) {
    return [fetchPageDataWorkspace({ tenantId, userId, pageCode: "institution_supervision" })];
  }
  if (path.startsWith("/customer-segment-analysis")) {
    return [
      fetchApplicationModule({ tenantId, userId, moduleKey: "customer_segment_analysis" }),
      fetchPageDataWorkspace({ tenantId, userId, pageCode: "customer_segment_analysis" }),
    ];
  }

  const moduleKey = applicationModuleForPath(path);
  return moduleKey ? [fetchApplicationModule({ tenantId, userId, moduleKey })] : [];
}

function applicationModuleForPath(path: string): ApplicationModuleKey | null {
  if (path === "/dashboard") return "dashboard";
  if (path.startsWith("/weekly-report")) return "weekly_report";
  if (path.startsWith("/supervision")) return "institution_supervision";
  if (path.startsWith("/customer-segment-analysis")) return "customer_segment_analysis";
  if (path.startsWith("/customers")) return "customer_insight";
  if (path.startsWith("/competition")) return "competition_analysis";
  if (path.startsWith("/agent/todos")) return "agent_workspace";
  if (path.startsWith("/notifications/")) return "notifications";
  return null;
}
