import { apiRequest } from "./apiClient";
import { getDefaultUserId } from "./apiContext";

export type AutomationTask = {
  tenant_id: string;
  automation_task_id: string;
  task_code: string;
  task_name: string;
  task_type: string;
  trigger_type: "manual" | "schedule" | "event";
  schedule_expression?: string | null;
  event_type?: string | null;
  handler_ref: string;
  task_config: Record<string, unknown>;
  retry_policy: Record<string, unknown>;
  timeout_seconds: number;
  max_concurrency: number;
  status: "active" | "paused" | "disabled";
  next_run_at?: string | null;
  owner_user_id: string;
  created_at: string;
  updated_at: string;
  lock_version: number;
};

export type AutomationRun = {
  tenant_id: string;
  automation_run_id: string;
  automation_task_id: string;
  status: "queued" | "running" | "retry_wait" | "succeeded" | "failed" | "cancelled";
  result_refs: Array<Record<string, unknown>>;
  error_code?: string | null;
  error_summary?: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
};

export async function fetchAutomationWorkspace({ tenantId, userId = getDefaultUserId() }: { tenantId: string; userId?: string }) {
  return apiRequest<{ handlers: string[]; tasks: AutomationTask[]; runs: AutomationRun[] }>("/api/automation", {
    method: "GET",
    context: { tenantId, userId },
  });
}

export async function createAutomationTask({
  tenantId,
  userId = getDefaultUserId(),
  definition,
}: {
  tenantId: string;
  userId?: string;
  definition: Record<string, unknown>;
}) {
  return apiRequest<{ task: AutomationTask }>("/api/automation/task", {
    method: "POST",
    context: { tenantId, userId },
    body: definition,
  });
}

export async function updateAutomationTask({
  tenantId,
  userId = getDefaultUserId(),
  taskId,
  expectedLockVersion,
  patch,
}: {
  tenantId: string;
  userId?: string;
  taskId: string;
  expectedLockVersion: number;
  patch: Record<string, unknown>;
}) {
  return apiRequest<{ task: AutomationTask }>("/api/automation/task", {
    method: "PUT",
    context: { tenantId, userId },
    body: { automation_task_id: taskId, expected_lock_version: expectedLockVersion, ...patch },
  });
}

export async function triggerAutomationTask({
  tenantId,
  userId = getDefaultUserId(),
  taskId,
  idempotencyKey,
}: {
  tenantId: string;
  userId?: string;
  taskId: string;
  idempotencyKey: string;
}) {
  return apiRequest<{ run: AutomationRun }>("/api/automation/run", {
    method: "POST",
    context: { tenantId, userId },
    headers: { "Idempotency-Key": idempotencyKey },
    body: { automation_task_id: taskId, idempotency_key: idempotencyKey, trigger_payload: {} },
  });
}
