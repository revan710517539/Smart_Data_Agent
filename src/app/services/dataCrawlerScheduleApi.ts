import { apiRequest } from "./apiClient";
import { getDefaultUserId } from "./apiContext";

export type DataCrawlerParameter = {
  name: string;
  label: string;
  type: "date" | "month" | "datetime" | "text" | "enum" | "boolean" | "integer" | "number";
  occurrenceCount: number;
  scheduleRules?: Array<{ value: string; label: string }>;
  defaultScheduleRule?: string;
};

export type DataCrawlerBinding = {
  institutionId: string;
  institutionName: string;
  sqlId: string;
  sqlName: string;
  parameters: DataCrawlerParameter[];
  defaultLoopEnabled: boolean;
  oneShot: boolean;
  latestDelivery?: { path?: string; sha256?: string; runId?: string; finishedAt?: string };
};

export type DataCrawlerScheduleState = {
  tenant_id: string;
  source_key: string;
  institution_id: string;
  institution_directory: string;
  validation_required: boolean;
  binding: DataCrawlerBinding | null;
  available_bindings: Array<Pick<DataCrawlerBinding, "sqlId" | "sqlName" | "parameters">>;
  task: null | {
    automation_task_id: string;
    status: string;
    trigger_type?: "manual" | "schedule" | "event";
    lock_version: number;
    task_config: {
      parameters?: Record<string, string>;
      parameter_bindings?: Record<string, string>;
      recurrence?: string;
      execution_at?: string;
      biweekly_anchor?: string;
    };
    schedule_expression?: string;
    next_run_at?: string | null;
  };
};

export type DataCrawlerScheduleListStatus = {
  scheduled: true;
  recurrence: string;
  schedule_expression: string;
  next_run_at: string;
};

export type DataCrawlerScheduleDraft = {
  recurrence: "none" | "daily" | "weekly" | "biweekly" | "monthly";
  executionAt: string;
  parameters: Record<string, string>;
  parameterBindings: Record<string, string>;
};

type Context = { tenantId: string; userId?: string };
type ScriptContext = { sourceKey?: string; sqlId: string };

export function fetchDataCrawlerSchedule({ tenantId, userId = getDefaultUserId(), sourceKey = "", sqlId }: Context & ScriptContext) {
  const query = new URLSearchParams({ source_key: sourceKey, sql_id: sqlId, view: "configuration" });
  return apiRequest<DataCrawlerScheduleState>(`/api/data-crawler-schedule?${query.toString()}`, {
    method: "GET",
    context: { tenantId, userId },
  });
}

export function fetchDataCrawlerScheduleStatuses({ tenantId, userId = getDefaultUserId() }: Context) {
  return apiRequest<{ items: Record<string, DataCrawlerScheduleListStatus>; count: number }>("/api/data-crawler-schedule/statuses", {
    method: "GET",
    context: { tenantId, userId },
    readCache: { ttlMs: 8_000, tags: ["data-crawler-schedule-statuses"] },
  });
}

function mutationBody(sourceKey: string | undefined, sqlId: string, draft: DataCrawlerScheduleDraft) {
  return { source_key: sourceKey || "", sql_id: sqlId, ...draft };
}

export function saveDataCrawlerSchedule({ tenantId, userId = getDefaultUserId(), sourceKey, sqlId, draft }: Context & ScriptContext & { draft: DataCrawlerScheduleDraft }) {
  return apiRequest<{ task: DataCrawlerScheduleState["task"] }>("/api/data-crawler-schedule", {
    method: "PUT",
    context: { tenantId, userId },
    body: mutationBody(sourceKey, sqlId, draft),
  });
}

export function testDataCrawlerSchedule({ tenantId, userId = getDefaultUserId(), sourceKey, sqlId, draft }: Context & ScriptContext & { draft: DataCrawlerScheduleDraft }) {
  return apiRequest<{ connected: true; institution_id: string; sql_id: string; parameter_count: number; run: { runId: string; status: string; message?: string; sqlId?: string } }>("/api/data-crawler-schedule/test", {
    method: "POST",
    context: { tenantId, userId },
    body: mutationBody(sourceKey, sqlId, draft),
  });
}

export function refreshDataCrawlerSchedule({ tenantId, userId = getDefaultUserId(), sourceKey, sqlId, draft }: Context & ScriptContext & { draft: DataCrawlerScheduleDraft }) {
  return apiRequest<{ binding: DataCrawlerBinding; refreshed: true; run: { runId: string; status: string; message?: string; sqlId?: string } }>("/api/data-crawler-schedule/refresh", {
    method: "POST",
    context: { tenantId, userId },
    body: mutationBody(sourceKey, sqlId, draft),
  });
}

export function executeDataCrawlerSchedule({ tenantId, userId = getDefaultUserId(), sourceKey, sqlId, draft }: Context & ScriptContext & { draft: DataCrawlerScheduleDraft }) {
  return apiRequest<{ task: DataCrawlerScheduleState["task"]; run: { automation_run_id: string; status: string } }>("/api/data-crawler-schedule/execute", {
    method: "POST",
    context: { tenantId, userId },
    body: mutationBody(sourceKey, sqlId, draft),
  });
}

export function fetchDataCrawlerScheduleExecution({ tenantId, userId = getDefaultUserId(), runId }: Context & { runId: string }) {
  const query = new URLSearchParams({ run_id: runId });
  return apiRequest<{ run: { runId: string; status: string; message?: string; sqlId?: string } }>(`/api/data-crawler-schedule/execution?${query.toString()}`, {
    method: "GET",
    context: { tenantId, userId },
  });
}

export function clearDataCrawlerSchedule({ tenantId, userId = getDefaultUserId(), sourceKey, sqlId }: Context & ScriptContext) {
  return apiRequest<{ cleared: boolean }>("/api/data-crawler-schedule", {
    method: "DELETE",
    context: { tenantId, userId },
    body: { source_key: sourceKey || "", sql_id: sqlId },
  });
}

export function fetchAutomationRun({ tenantId, userId = getDefaultUserId(), runId }: Context & { runId: string }) {
  const query = new URLSearchParams({ run_id: runId });
  return apiRequest<{ run: { status: string; error_summary?: string; result_refs?: Record<string, string> } }>(`/api/automation/run?${query.toString()}`, {
    method: "GET",
    context: { tenantId, userId },
  });
}
