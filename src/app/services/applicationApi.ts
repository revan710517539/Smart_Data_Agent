import { apiRequest } from "./apiClient";
import { getDefaultTenantId, getDefaultUserId } from "./apiContext";

export type ApplicationModuleKey =
  | "dashboard"
  | "business_funnel"
  | "business_sandbox"
  | "customer_insight"
  | "single_customer_insight"
  | "competition_analysis"
  | "institution_supervision"
  | "email_daily"
  | "agent_workspace"
  | "notifications"
  | "weekly_report"
  | "self_analysis"
  | "platform_shell";

export type ApplicationActionRecord = {
  id: string;
  moduleKey: ApplicationModuleKey;
  action: string;
  status: string;
  payload: Record<string, unknown>;
  result: Record<string, unknown>;
  createdBy: string;
  createdAt: string;
};

export type ApplicationModuleResponse<TState extends Record<string, unknown> = Record<string, unknown>> = {
  tenant_id: string;
  module_key: ApplicationModuleKey;
  state: TState;
  actions: ApplicationActionRecord[];
  updated_at: string;
};

export type ApplicationActionResponse<TState extends Record<string, unknown> = Record<string, unknown>> = {
  tenant_id: string;
  module_key: ApplicationModuleKey;
  action: ApplicationActionRecord;
  result: Record<string, unknown>;
  module: ApplicationModuleResponse<TState>;
};

type ContextParams = {
  tenantId?: string;
  userId?: string;
};

export async function fetchApplicationModule<TState extends Record<string, unknown> = Record<string, unknown>>({
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
  moduleKey,
}: ContextParams & {
  moduleKey: ApplicationModuleKey;
}) {
  const params = new URLSearchParams({ module_key: moduleKey });
  return apiRequest<ApplicationModuleResponse<TState>>(`/api/application/module?${params.toString()}`, {
    method: "GET",
    context: { tenantId, userId },
    readCache: { ttlMs: 8_000, tags: ["application", `application:${moduleKey}`] },
  });
}

export async function runApplicationAction<TState extends Record<string, unknown> = Record<string, unknown>>({
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
  moduleKey,
  action,
  payload = {},
}: ContextParams & {
  moduleKey: ApplicationModuleKey;
  action: string;
  payload?: Record<string, unknown>;
}) {
  return apiRequest<ApplicationActionResponse<TState>>("/api/application/action", {
    method: "POST",
    context: { tenantId, userId },
    body: {
      module_key: moduleKey,
      action,
      payload,
    },
  });
}
