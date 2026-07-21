import { ApiRequestError, apiRequest } from "./apiClient";
import { getDefaultUserId } from "./apiContext";

export type ModelIntegration = {
  id: string;
  name: string;
  modelName: string;
  key: string;
  value: string;
  applicationModule?: string;
  availableModels?: string[];
  enabledModels?: string[];
  selectedModelName?: string;
  lastTestedAt?: string;
  testStatus?: "untested" | "connected" | "failed" | "mock";
  testMessage?: string;
  testResponse?: string;
  status: "available" | "draft";
};

export type SpeechIntegration = {
  id: string;
  name: string;
  provider: "aliyun_fun_asr" | string;
  source?: string;
  apiBase: string;
  apiKey: string;
  applicationModule?: string;
  lastTestedAt?: string;
  testStatus?: "untested" | "connected" | "failed" | "mock";
  testMessage?: string;
  testResponse?: string;
  status: "available" | "draft";
};

export type FunAsrRuntimeIntegration = Pick<SpeechIntegration, "id" | "name" | "provider" | "applicationModule" | "status" | "testStatus">;

export async function fetchAnalysisRuntimeConfig({
  tenantId,
  userId = getDefaultUserId(),
  speechApplicationModule = "",
}: SystemConfigParams & { speechApplicationModule?: string }): Promise<{ speechIntegration: FunAsrRuntimeIntegration | null; models: ModelIntegration[] }> {
  const params = new URLSearchParams({ tenant_id: tenantId, user_id: userId });
  if (speechApplicationModule) params.set("application_module", speechApplicationModule);
  const path = `/api/asr/fun-asr/runtime-config?${params.toString()}`;
  type RuntimeConfigResponse = {
    available: boolean;
    provider: "aliyun_fun_asr";
    integration: FunAsrRuntimeIntegration | null;
    analysisModels: ModelIntegration[];
  };
  let response: RuntimeConfigResponse;
  try {
    response = await apiRequest<RuntimeConfigResponse>(path, { method: "GET" });
  } catch (error) {
    if (!isRetryableRuntimeConfigError(error)) throw error;
    await new Promise<void>((resolve) => window.setTimeout(resolve, 250));
    response = await apiRequest<RuntimeConfigResponse>(path, { method: "GET" });
  }
  return {
    speechIntegration: response.available ? response.integration : null,
    models: response.analysisModels || [],
  };
}

function isRetryableRuntimeConfigError(error: unknown) {
  if (!(error instanceof ApiRequestError)) return false;
  return error.status === 0 || [401, 403, 408, 429, 502, 503, 504].includes(error.status);
}

export type DataConnection = {
  id: string;
  institution: string;
  sourceName: string;
  sourceType: "QBI" | "API" | "JDBC" | "file" | "mock" | string;
  apiUrl: string;
  loginUrl?: string;
  queryPageUrl?: string;
  metadataPageUrl?: string;
  spaceId?: string;
  crawlerMode?: "page" | "sql" | "";
  crawlerKey?: string;
  crawlerProfileId?: string;
  account: string;
  password: string;
  token: string;
  dataset: string;
  defaultDatabase: string;
  enabled: boolean;
  mockEnabled: boolean;
  lastTestedAt?: string;
  testStatus?: "untested" | "testing" | "verified" | "failed" | "mock";
  testMessage?: string;
  status: "connected" | "draft" | "verified" | "degraded" | "disabled" | "mock";
};

export type SystemDataParam = {
  id: string;
  name: string;
  value: string;
  category: "data" | "security" | "system" | string;
  description: string;
};

export type DataConnectionTestResult = {
  connection_id: string;
  institution: string;
  dataset: string;
  status: "verified" | "mock" | "endpoint_required" | "egress_policy_rejected" | "connection_failed" | "not_found" | "schema_incomplete" | "query_failed" | "transport_not_configured" | "manual_intervention_required" | string;
  callable: boolean;
  verified?: boolean;
  execution_mode?: "real" | "mock";
  data_source_mode: string;
  matched_dataset?: {
    dataset_id: string;
    label: string;
    source_table: string;
    metric_count: number;
    dimension_count: number;
  } | null;
  available_datasets: Array<{
    dataset_id: string;
    label: string;
    source_table: string;
    metric_count: number;
    dimension_count: number;
  }>;
  sample?: {
    row_count: number;
    rows: Array<Record<string, unknown>>;
  };
  message: string;
  diagnostics?: Record<string, unknown>;
};

export type ModelIntegrationTestResult = {
  model_id: string;
  model_name: string;
  source: string;
  callable: boolean;
  status: "connected" | "failed";
  message: string;
  available_models: string[];
  response_preview: string;
  used_model?: string;
  error_code?: string;
  transient?: boolean;
  preserved_last_known_good?: boolean;
  latency_ms?: number;
  tested_at: string;
};

export type SpeechIntegrationTestResult = {
  integration_id: string;
  name: string;
  provider: string;
  source: string;
  callable: boolean;
  status: "connected" | "failed";
  message: string;
  endpoint: string;
  response_preview: string;
  tested_at: string;
};

type SystemConfigParams = {
  tenantId: string;
  userId?: string;
};

type SystemConfigResponse = {
  tenant_id: string;
  config_scope?: string;
  config_owner_user_id?: string;
  models: ModelIntegration[];
  speech_integrations: SpeechIntegration[];
  data_connections: DataConnection[];
  system_params: SystemDataParam[];
  count: {
    models: number;
    speech_integrations: number;
    data_connections: number;
    system_params: number;
  };
};

const SYSTEM_CONFIG_CACHE_TTL_MS = 5_000;
const systemConfigCache = new Map<string, { expiresAt: number; value: SystemConfigResponse }>();
const systemConfigRequests = new Map<string, Promise<SystemConfigResponse>>();

function systemConfigCacheKey(tenantId: string, userId: string) {
  return `${tenantId.trim()}::${userId.trim()}`;
}

function invalidateSystemConfig(tenantId: string, userId: string) {
  const key = systemConfigCacheKey(tenantId, userId);
  systemConfigCache.delete(key);
  systemConfigRequests.delete(key);
}

export async function fetchSystemConfig({
  tenantId,
  userId = getDefaultUserId(),
  forceRefresh = false,
}: SystemConfigParams & { forceRefresh?: boolean }): Promise<SystemConfigResponse> {
  const cacheKey = systemConfigCacheKey(tenantId, userId);
  const cached = systemConfigCache.get(cacheKey);
  if (!forceRefresh && cached && cached.expiresAt > Date.now()) return cached.value;
  const pending = systemConfigRequests.get(cacheKey);
  if (pending) return pending;

  const request = apiRequest<SystemConfigResponse>("/api/system-config", {
    method: "GET",
    context: { tenantId, userId },
    timeoutMs: 15_000,
  })
    .then((value) => {
      systemConfigCache.set(cacheKey, { value, expiresAt: Date.now() + SYSTEM_CONFIG_CACHE_TTL_MS });
      return value;
    })
    .finally(() => systemConfigRequests.delete(cacheKey));
  systemConfigRequests.set(cacheKey, request);
  return request;
}

export async function saveModelIntegration({
  tenantId,
  userId = getDefaultUserId(),
  model,
}: SystemConfigParams & { model: ModelIntegration }): Promise<{ tenant_id: string; model: ModelIntegration }> {
  const response = await apiRequest<{ tenant_id: string; model: ModelIntegration }>("/api/system-config/model", {
    method: "POST",
    context: { tenantId, userId },
    body: { model },
  });
  invalidateSystemConfig(tenantId, userId);
  return response;
}

export async function deleteModelIntegration({
  tenantId,
  userId = getDefaultUserId(),
  modelId,
}: SystemConfigParams & { modelId: string }): Promise<{ tenant_id: string; model_id: string; deleted: boolean }> {
  const params = new URLSearchParams({ model_id: modelId });
  const response = await apiRequest<{ tenant_id: string; model_id: string; deleted: boolean }>(
    `/api/system-config/model?${params.toString()}`,
    {
      method: "DELETE",
      context: { tenantId, userId },
    },
  );
  invalidateSystemConfig(tenantId, userId);
  return response;
}

export async function testModelIntegration({
  tenantId,
  userId = getDefaultUserId(),
  modelId,
  model,
}: SystemConfigParams & { modelId?: string; model?: ModelIntegration }): Promise<{ tenant_id: string; result: ModelIntegrationTestResult; model?: ModelIntegration }> {
  const response = await apiRequest<{ tenant_id: string; result: ModelIntegrationTestResult; model?: ModelIntegration }>("/api/system-config/model/test", {
    method: "POST",
    context: { tenantId, userId },
    body: { model_id: modelId, model },
    // The backend performs model discovery and one real completion inside a
    // bounded 50-second probe.  Keep the browser budget slightly larger so it
    // receives the classified provider result instead of aborting at 12s.
    timeoutMs: 65_000,
  });
  invalidateSystemConfig(tenantId, userId);
  return response;
}

export async function testSpeechIntegration({
  tenantId,
  userId = getDefaultUserId(),
  integrationId,
  speechIntegration,
}: SystemConfigParams & { integrationId?: string; speechIntegration?: SpeechIntegration }): Promise<{ tenant_id: string; result: SpeechIntegrationTestResult; speech_integration?: SpeechIntegration }> {
  return apiRequest<{ tenant_id: string; result: SpeechIntegrationTestResult; speech_integration?: SpeechIntegration }>("/api/system-config/speech-integration/test", {
    method: "POST",
    context: { tenantId, userId },
    body: { integration_id: integrationId, speech_integration: speechIntegration },
  });
}

export async function saveSpeechIntegration({
  tenantId,
  userId = getDefaultUserId(),
  speechIntegration,
}: SystemConfigParams & { speechIntegration: SpeechIntegration }): Promise<{ tenant_id: string; speech_integration: SpeechIntegration }> {
  return apiRequest<{ tenant_id: string; speech_integration: SpeechIntegration }>("/api/system-config/speech-integration", {
    method: "POST",
    context: { tenantId, userId },
    body: { speech_integration: speechIntegration },
  });
}

export async function deleteSpeechIntegration({
  tenantId,
  userId = getDefaultUserId(),
  integrationId,
}: SystemConfigParams & { integrationId: string }): Promise<{ tenant_id: string; integration_id: string; deleted: boolean }> {
  const params = new URLSearchParams({ integration_id: integrationId });
  return apiRequest<{ tenant_id: string; integration_id: string; deleted: boolean }>(
    `/api/system-config/speech-integration?${params.toString()}`,
    {
      method: "DELETE",
      context: { tenantId, userId },
    },
  );
}

export async function saveDataConnection({
  tenantId,
  userId = getDefaultUserId(),
  connection,
}: SystemConfigParams & { connection: DataConnection }): Promise<{ tenant_id: string; connection: DataConnection }> {
  return apiRequest<{ tenant_id: string; connection: DataConnection }>("/api/system-config/data-connection", {
    method: "POST",
    context: { tenantId, userId },
    body: { connection },
  });
}

export async function deleteDataConnection({
  tenantId,
  userId = getDefaultUserId(),
  connectionId,
}: SystemConfigParams & { connectionId: string }): Promise<{ tenant_id: string; connection_id: string; deleted: boolean }> {
  const params = new URLSearchParams({ connection_id: connectionId });
  return apiRequest<{ tenant_id: string; connection_id: string; deleted: boolean }>(
    `/api/system-config/data-connection?${params.toString()}`,
    {
      method: "DELETE",
      context: { tenantId, userId },
    },
  );
}

export async function testDataConnection({
  tenantId,
  userId = getDefaultUserId(),
  connectionId,
  connection,
}: SystemConfigParams & { connectionId?: string; connection?: DataConnection }): Promise<{ tenant_id: string; result: DataConnectionTestResult }> {
  return apiRequest<{ tenant_id: string; result: DataConnectionTestResult }>("/api/system-config/data-connection/test", {
    method: "POST",
    context: { tenantId, userId },
    body: { connection_id: connectionId, connection },
  });
}

export async function saveSystemDataParam({
  tenantId,
  userId = getDefaultUserId(),
  param,
}: SystemConfigParams & { param: SystemDataParam }): Promise<{ tenant_id: string; param: SystemDataParam }> {
  return apiRequest<{ tenant_id: string; param: SystemDataParam }>("/api/system-config/system-param", {
    method: "POST",
    context: { tenantId, userId },
    body: { param },
  });
}
