import { ApiRequestError, apiRequest } from "./apiClient";
import { getDefaultTenantId, getDefaultUserId } from "./apiContext";
import { createClientUuid } from "../utils/clientUuid";

export type BackendAnalysisPlan = {
  dataset_id?: string;
  metrics?: string[];
  dimensions?: string[];
  filters?: Record<string, unknown>;
  chart_types?: string[];
  analysis_angles?: string[];
  business_focus?: string;
  metric_definitions?: BackendMetricDefinition[];
  model_planning?: BackendModelPlanning;
};

export type BackendMetricDefinition = {
  metric_code?: string;
  metric_name?: string;
  aggregation?: string;
  numerator?: string;
  denominator?: string;
  multiplier?: number;
  unit?: string;
  grain?: string;
  source?: string;
  version?: string;
};

export type BackendModelInvocation = {
  status?: string;
  callable?: boolean;
  message?: string;
  error_code?: string;
  used_model?: string;
  model_id?: string;
  prompt_template_id?: string;
  retry_count?: number;
  initial_error_code?: string;
};

export type BackendMetricScenario = {
  metric?: string;
  positive?: string;
  neutral?: string;
  negative?: string;
};

export type BackendVisualizationSuggestion = {
  type?: string;
  title?: string;
  dimension?: string;
  metric?: string;
  purpose?: string;
};

export type BackendModelPlanning = {
  planning_source?: string;
  metrics?: string[];
  dimensions?: string[];
  limit?: number;
  sort_direction?: string;
  sql?: string;
  python_script?: string;
  data_processing_python?: string;
  visualization_python?: string;
  analysis_approach?: string[];
  metric_scenarios?: BackendMetricScenario[];
  visualization_suggestions?: BackendVisualizationSuggestion[];
  validation_errors?: string[];
  planning_invocation?: BackendModelInvocation;
};

export type BackendSkillResult = {
  sql?: string;
  parameters?: Record<string, unknown>;
  data?: Array<Record<string, unknown>>;
  python_script?: string;
  data_processing_python_script?: string;
  data_processing_artifact?: {
    input_row_count?: number;
    output_row_count?: number;
    metric_definitions_bound?: boolean;
    metric_definition_versions?: Record<string, string>;
    totals?: Record<string, number>;
  };
  visualization_artifact?: {
    type?: string;
    title?: string;
    x?: string;
    y?: string;
    series?: Array<{
      name?: string;
      value?: number;
      metric_id?: string;
      raw?: Record<string, unknown>;
    }>;
    table_rows?: Array<Record<string, unknown>>;
    analysis_angles?: string[];
    business_focus?: string;
    runtime?: string;
  };
  chart_spec?: {
    type?: string;
    x?: string;
    y?: string;
    title?: string;
  };
  visualization_spec?: {
    chart_type?: string;
    title?: string;
    x?: string;
    y?: string[];
    series?: string;
    orientation?: "horizontal" | "vertical" | string;
    reason?: string;
    alternatives?: string[];
    unit?: string;
    precision?: number;
    interactions?: string[];
    pivot?: Record<string, unknown> | null;
  };
  semantic_info?: Record<string, unknown>;
  evidence?: {
    evidence_id?: string;
    data_source?: string;
    source_snapshot?: Record<string, unknown>;
    executed_sql_sha256?: string;
    [key: string]: unknown;
  };
  intelligent_analysis?: BackendIntelligentAnalysis;
};

export type BackendIntelligentAnalysis = {
  sql?: string;
  python_script?: string;
  planning?: BackendModelPlanning;
  suggested_sql?: string;
  executed_sql?: string;
  suggested_python_script?: string;
  suggested_data_processing_python?: string;
  suggested_visualization_python?: string;
  visualization_suggestions?: BackendVisualizationSuggestion[];
  analysis_approach?: string[];
  metric_scenarios?: BackendMetricScenario[];
  metric_findings?: Array<Record<string, unknown>>;
  possible_conclusions?: string[];
  analysis_summary?: string;
  planning_invocation?: BackendModelInvocation;
  model_invocation?: BackendModelInvocation;
  model_draft?: string;
  context?: Record<string, unknown>;
  conclusion_coverage?: {
    metrics_covered?: string[];
    dimensions_covered?: string[];
    zero_value_groups?: Record<string, number>;
    returned_group_count?: number;
    full_group_count?: number;
    limitations?: string[];
  };
};

export type BackendAnalysisResponse = {
  task_id: string;
  question?: string;
  created_at?: string;
  updated_at?: string;
  execution_id?: string;
  revision?: number;
  parent_execution_id?: string | null;
  request_id?: string;
  status?: string;
  manual_edits?: Record<string, { status?: string; reason?: string }>;
  task_type: string;
  analysis_plan?: BackendAnalysisPlan;
  plan?: Array<Record<string, unknown>>;
  skill_results?: BackendSkillResult[];
  knowledge_refs?: Array<Record<string, unknown>>;
  conclusions?: string[];
  review?: Record<string, unknown>;
  trace_id?: string;
  asset_context?: Record<string, unknown>;
  intelligent_analysis?: BackendIntelligentAnalysis;
  workspace_turn?: Record<string, unknown>;
};

type RunSelfAnalysisParams = {
  question: string;
  tenantId?: string;
  userId?: string;
  pageContext?: Record<string, unknown>;
  requestId?: string;
};

export async function runSelfAnalysis({
  question,
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
  pageContext = {},
  requestId,
}: RunSelfAnalysisParams): Promise<BackendAnalysisResponse> {
  return apiRequest<BackendAnalysisResponse>("/api/analysis/run", {
    method: "POST",
    context: { tenantId, userId },
    headers: requestId ? { "Idempotency-Key": requestId } : undefined,
    body: {
      question,
      page_context: pageContext,
    },
    timeoutMs: 60000,
  });
}

export type AsyncAnalysisRun = {
  automation_run_id: string;
  status: "queued" | "running" | "retry_wait" | "succeeded" | "failed" | "cancelled";
  result_refs?: Array<{
    type?: string;
    id?: string;
    hash?: string;
    details?: AnalysisContractErrorDetails;
  }>;
  error_code?: string | null;
  error_summary?: string | null;
  error_details?: AnalysisContractErrorDetails;
  progress_steps?: AnalysisProgressStep[];
};

export type AnalysisContractErrorDetails = {
  error: string;
  stage: string;
  missingFields: Array<{ canonicalId: string; displayName: string; expectedKey: string }>;
  fieldDifferences: Array<{
    canonicalId: string;
    displayName: string;
    change: string;
    previous: string;
    current: string;
  }>;
  requiredFields: string[];
  availableFields: string[];
  asset: Record<string, string>;
  retryable: boolean;
  userAction: string;
  requestId: string;
};

export type AnalysisProgressStep = {
  step_code: string;
  sequence_no: number;
  status: "queued" | "running" | "succeeded" | "failed" | "skipped" | string;
  output_refs?: Array<{
    label?: string;
    detail?: string;
    row_count?: number;
    partial_task_id?: string;
    task_id?: string;
    [key: string]: unknown;
  }>;
  error_code?: string | null;
  started_at?: string;
  finished_at?: string | null;
  updated_at?: string;
};

export async function enqueueSelfAnalysis({
  question,
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
  pageContext = {},
  requestId = createClientUuid(),
}: RunSelfAnalysisParams): Promise<AsyncAnalysisRun> {
  const response = await apiRequest<{ tenant_id: string; run: AsyncAnalysisRun }>("/api/analysis/run-async", {
    method: "POST",
    context: { tenantId, userId },
    headers: { "Idempotency-Key": requestId },
    body: { question, page_context: pageContext, request_id: requestId },
  });
  return response.run;
}

export async function fetchAsyncAnalysisRun({
  runId,
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
}: {
  runId: string;
  tenantId?: string;
  userId?: string;
}): Promise<AsyncAnalysisRun> {
  const params = new URLSearchParams({ run_id: runId });
  const response = await apiRequest<{ tenant_id: string; run: AsyncAnalysisRun }>(
    `/api/analysis/run-status?${params.toString()}`,
    { method: "GET", context: { tenantId, userId } },
  );
  return response.run;
}

export async function cancelAsyncAnalysisRun({
  runId,
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
}: {
  runId: string;
  tenantId?: string;
  userId?: string;
}): Promise<AsyncAnalysisRun> {
  const response = await apiRequest<{ tenant_id: string; run: AsyncAnalysisRun }>("/api/analysis/run-cancel", {
    method: "POST",
    context: { tenantId, userId },
    body: { automation_run_id: runId },
  });
  return response.run;
}

export type AnalysisTraceSpan = {
  span_id: string;
  trace_id: string;
  span_name: string;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  status: string;
  created_at: string;
};

export async function fetchAnalysisHistory({
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
  limit = 50,
}: { tenantId?: string; userId?: string; limit?: number }) {
  const params = new URLSearchParams({ limit: String(limit) });
  return apiRequest<{ tenant_id: string; tasks: BackendAnalysisResponse[]; count: number }>(`/api/analysis/history?${params.toString()}`, {
    method: "GET",
    context: { tenantId, userId },
  });
}

export async function fetchAnalysisHistoryDetail({
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
  taskId,
}: { tenantId?: string; userId?: string; taskId: string }) {
  const params = new URLSearchParams({ task_id: taskId });
  return apiRequest<{ tenant_id: string; task: BackendAnalysisResponse; spans: AnalysisTraceSpan[] }>(`/api/analysis/history?${params.toString()}`, {
    method: "GET",
    context: { tenantId, userId },
  });
}

export async function deleteAnalysisHistoryTask({
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
  taskId,
}: { tenantId?: string; userId?: string; taskId: string }) {
  const params = new URLSearchParams({ task_id: taskId });
  return apiRequest<{ tenant_id: string; task_id: string; deleted: boolean }>(`/api/analysis/history?${params.toString()}`, {
    method: "DELETE",
    context: { tenantId, userId },
  });
}

export async function waitForSelfAnalysis({
  question,
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
  pageContext = {},
  requestId = createClientUuid(),
  onRun,
  resumeRunId,
  signal,
  pollIntervalMs = 1_500,
  deadlineMs = 15 * 60 * 1000,
}: RunSelfAnalysisParams & {
  onRun?: (run: AsyncAnalysisRun) => void;
  resumeRunId?: string;
  signal?: AbortSignal;
  pollIntervalMs?: number;
  deadlineMs?: number;
}): Promise<BackendAnalysisResponse> {
  throwIfAnalysisWaitAborted(signal);
  let run = resumeRunId
    ? await fetchAsyncAnalysisRun({ runId: resumeRunId, tenantId, userId })
    : await enqueueSelfAnalysis({ question, tenantId, userId, pageContext, requestId });
  onRun?.(run);
  throwIfAnalysisWaitAborted(signal);
  const deadline = Date.now() + deadlineMs;
  while (!["succeeded", "failed", "cancelled"].includes(run.status)) {
    if (Date.now() >= deadline) throw new ApiRequestError("analysis_deadline_exceeded", 0, "analysis_deadline_exceeded");
    await waitForAnalysisPoll(pollIntervalMs, signal);
    try {
      run = await fetchAsyncAnalysisRun({ runId: run.automation_run_id, tenantId, userId });
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 429) {
        const payload = error.payload as { retry_after_seconds?: number } | null;
        const retryAfterSeconds = Number(payload?.retry_after_seconds || 2);
        const retryDelayMs = Math.min(60_000, Math.max(1_500, retryAfterSeconds * 1_000));
        await waitForAnalysisPoll(retryDelayMs, signal);
        continue;
      }
      throw error;
    }
    onRun?.(run);
    throwIfAnalysisWaitAborted(signal);
  }
  if (run.status !== "succeeded") {
    throw new ApiRequestError(
      run.error_summary || run.error_code || `analysis_${run.status}`,
      0,
      run.error_code || `analysis_${run.status}`,
      run,
    );
  }
  const taskRef = run.result_refs?.find((ref) => ref.type === "task" && ref.id);
  if (!taskRef?.id) throw new ApiRequestError("analysis_task_reference_missing", 0, "analysis_task_reference_missing", run);
  const task = await fetchAnalysisTask({ taskId: taskRef.id, tenantId, userId });
  throwIfAnalysisWaitAborted(signal);
  return task;
}

function throwIfAnalysisWaitAborted(signal?: AbortSignal) {
  if (signal?.aborted) throw new DOMException("analysis_wait_aborted", "AbortError");
}

function waitForAnalysisPoll(delayMs: number, signal?: AbortSignal): Promise<void> {
  throwIfAnalysisWaitAborted(signal);
  return new Promise((resolve, reject) => {
    const timeoutId = window.setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, delayMs);
    const abort = () => {
      window.clearTimeout(timeoutId);
      signal?.removeEventListener("abort", abort);
      reject(new DOMException("analysis_wait_aborted", "AbortError"));
    };
    signal?.addEventListener("abort", abort, { once: true });
  });
}

export async function fetchAnalysisTask({
  taskId,
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
}: {
  taskId: string;
  tenantId?: string;
  userId?: string;
}): Promise<BackendAnalysisResponse> {
  const params = new URLSearchParams({ task_id: taskId });
  const response = await apiRequest<{ tenant_id: string; task: BackendAnalysisResponse }>(
    `/api/analysis/task?${params.toString()}`,
    { method: "GET", context: { tenantId, userId } },
  );
  return response.task;
}
