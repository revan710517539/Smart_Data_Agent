import { apiRequest } from "./apiClient";
import { getDefaultUserId } from "./apiContext";

export type ReportSource = {
  channel: string;
  label: string;
  bindingId?: string;
  runId?: string;
  reportId?: string;
  url?: string;
};

export type SavedAnalysisResult = {
  id: string;
  title: string;
  query: string;
  plan: string;
  summary: string;
  visualTypes: {
    primary: string;
    secondary: string;
  };
  visualizations?: Array<{
    id: string;
    key?: "primary" | "secondary";
    title: string;
    type: string;
    config?: {
      metricFields: string[];
      dimensionFields: string[];
      filters: Record<string, string[]>;
      filterGroups?: Array<{
        id: string;
        rules: Array<{
          id: string;
          field: string;
          operator: "in" | "not_in" | "contains" | "not_contains";
          values: string[];
        }>;
      }>;
      sumFilteredRows: boolean;
      comboLineFields: string[];
    };
  }>;
  savedAt: string;
  rows: unknown[];
  analysisTaskId: string;
  sql?: string;
  pythonScript?: string;
  analysisScenarios?: string;
  selectedDataTables?: unknown[];
  ownerUserId?: string;
  visibility?: "private" | "tenant";
  updatedBy?: string;
  source?: ReportSource | null;
  weeklyReportEligible?: boolean;
  weeklyReportSavedAt?: string;
  topicData?: {
    reference_type: "history" | "shortcut" | "topic" | "report";
    reference_id: string;
    folder: string;
    updated_at: string;
    row_count: number;
    has_data: boolean;
    version_count: 1;
  };
};

export type ReportComment = Record<string, unknown>;
export type WeeklyReportVersionPayload = Record<string, unknown>;
export type WeeklyLearningTask = {
  id: string;
  version_id: string;
  status: string;
  input_snapshot?: Record<string, unknown>;
  debate_result?: Record<string, unknown>;
  final_result?: Record<string, unknown>;
  error_message?: string;
  created_at?: string;
  updated_at?: string;
};

type ReportParams = {
  tenantId: string;
  userId?: string;
};

type SavedAnalysisResultsResponse = {
  tenant_id: string;
  results: SavedAnalysisResult[];
  count: number;
};

type ReportCommentsResponse = {
  tenant_id: string;
  report_id: string;
  comments: ReportComment[];
  count: number;
  revision: number;
};

type ReportCommentMutationResponse = ReportCommentsResponse & {
  comment: ReportComment;
  idempotent_replay?: boolean;
};

type WeeklyVersionsResponse = {
  tenant_id: string;
  versions: WeeklyReportVersionPayload[];
  analysis_tasks: WeeklyLearningTask[];
  count: number;
};

export async function fetchSavedAnalysisResults({
  tenantId,
  userId = getDefaultUserId(),
}: ReportParams): Promise<SavedAnalysisResultsResponse> {
  return apiRequest<SavedAnalysisResultsResponse>("/api/reports/analysis-results", {
    method: "GET",
    context: { tenantId, userId },
    readCache: { ttlMs: 10_000, tags: ["saved-analysis-results"] },
  });
}

export async function saveSavedAnalysisResult({
  tenantId,
  userId = getDefaultUserId(),
  result,
}: ReportParams & { result: SavedAnalysisResult }): Promise<{ tenant_id: string; result: SavedAnalysisResult }> {
  return apiRequest<{ tenant_id: string; result: SavedAnalysisResult }>("/api/reports/analysis-result", {
    method: "POST",
    context: { tenantId, userId },
    body: { result },
  });
}

export async function deleteSavedAnalysisResult({
  tenantId,
  userId = getDefaultUserId(),
  resultId,
}: ReportParams & { resultId: string }): Promise<{ tenant_id: string; result_id: string; deleted: boolean }> {
  const params = new URLSearchParams({ result_id: resultId });
  return apiRequest<{ tenant_id: string; result_id: string; deleted: boolean }>(
    `/api/reports/analysis-result?${params.toString()}`,
    {
      method: "DELETE",
      context: { tenantId, userId },
    },
  );
}

export async function saveAnalysisResultToWeeklyReport({
  tenantId,
  userId = getDefaultUserId(),
  resultId,
  weeklyReportEligible = true,
}: ReportParams & { resultId: string; weeklyReportEligible?: boolean }): Promise<{ tenant_id: string; result: SavedAnalysisResult }> {
  return apiRequest<{ tenant_id: string; result: SavedAnalysisResult }>("/api/reports/analysis-result/save-weekly", {
    method: "POST",
    context: { tenantId, userId },
    body: { result_id: resultId, weeklyReportEligible },
  });
}

export async function saveAnalysisResultAsExperience({
  tenantId,
  userId = getDefaultUserId(),
  resultId,
}: ReportParams & { resultId: string }): Promise<{ tenant_id: string; record: { memory_id: string; status: string }; idempotent: boolean; message: string }> {
  return apiRequest<{ tenant_id: string; record: { memory_id: string; status: string }; idempotent: boolean; message: string }>("/api/reports/analysis-result/save-experience", {
    method: "POST",
    context: { tenantId, userId },
    body: { result_id: resultId },
  });
}

export async function fetchReportComments({
  tenantId,
  userId = getDefaultUserId(),
  reportId,
}: ReportParams & { reportId: string }): Promise<ReportCommentsResponse> {
  const params = new URLSearchParams({ report_id: reportId });
  return apiRequest<ReportCommentsResponse>(`/api/reports/comments?${params.toString()}`, {
    method: "GET",
    context: { tenantId, userId },
  });
}

export async function replaceReportComments({
  tenantId,
  userId = getDefaultUserId(),
  reportId,
  comments,
  expectedRevision,
}: ReportParams & { reportId: string; comments: ReportComment[]; expectedRevision?: number }): Promise<ReportCommentsResponse> {
  return apiRequest<ReportCommentsResponse>("/api/reports/comments", {
    method: "PUT",
    context: { tenantId, userId },
    body: { report_id: reportId, comments, expected_revision: expectedRevision },
  });
}

export async function createReportComment({
  tenantId,
  userId = getDefaultUserId(),
  reportId,
  comment,
  expectedRevision,
  clientRequestId,
}: ReportParams & {
  reportId: string;
  comment: ReportComment;
  expectedRevision: number;
  clientRequestId: string;
}): Promise<ReportCommentMutationResponse> {
  return apiRequest<ReportCommentMutationResponse>("/api/reports/comment", {
    method: "POST",
    context: { tenantId, userId },
    headers: { "Idempotency-Key": clientRequestId },
    body: {
      report_id: reportId,
      comment,
      expected_revision: expectedRevision,
      client_request_id: clientRequestId,
    },
  });
}

export async function mutateReportComment({
  tenantId,
  userId = getDefaultUserId(),
  reportId,
  commentId,
  action,
  payload = {},
  expectedRevision,
  clientRequestId,
}: ReportParams & {
  reportId: string;
  commentId: string;
  action: "resolve" | "reopen" | "reply";
  payload?: Record<string, unknown>;
  expectedRevision: number;
  clientRequestId?: string;
}): Promise<ReportCommentMutationResponse> {
  return apiRequest<ReportCommentMutationResponse>("/api/reports/comment", {
    method: "PUT",
    context: { tenantId, userId },
    headers: clientRequestId ? { "Idempotency-Key": clientRequestId } : undefined,
    body: {
      report_id: reportId,
      comment_id: commentId,
      action,
      payload,
      expected_revision: expectedRevision,
      client_request_id: clientRequestId,
    },
  });
}

export async function deleteReportComment({
  tenantId,
  userId = getDefaultUserId(),
  reportId,
  commentId,
  expectedRevision,
}: ReportParams & {
  reportId: string;
  commentId: string;
  expectedRevision: number;
}): Promise<ReportCommentMutationResponse> {
  return apiRequest<ReportCommentMutationResponse>("/api/reports/comment", {
    method: "DELETE",
    context: { tenantId, userId },
    body: { report_id: reportId, comment_id: commentId, expected_revision: expectedRevision },
  });
}

export async function fetchWeeklyReportVersions({
  tenantId,
  userId = getDefaultUserId(),
}: ReportParams): Promise<WeeklyVersionsResponse> {
  return apiRequest<WeeklyVersionsResponse>("/api/reports/weekly-versions", {
    method: "GET",
    context: { tenantId, userId },
  });
}

export async function saveWeeklyReportVersion({
  tenantId,
  userId = getDefaultUserId(),
  version,
  analyze = true,
}: ReportParams & {
  version: WeeklyReportVersionPayload;
  analyze?: boolean;
}): Promise<{ tenant_id: string; version: WeeklyReportVersionPayload; analysis_task: WeeklyLearningTask | null }> {
  return apiRequest<{ tenant_id: string; version: WeeklyReportVersionPayload; analysis_task: WeeklyLearningTask | null }>(
    "/api/reports/weekly-version",
    {
      method: "POST",
      context: { tenantId, userId },
      body: { version, analyze },
    },
  );
}

export async function analyzeWeeklyReportVersion({
  tenantId,
  userId = getDefaultUserId(),
  versionId,
  force = true,
}: ReportParams & {
  versionId: string;
  force?: boolean;
}): Promise<{ tenant_id: string; analysis_task: WeeklyLearningTask }> {
  return apiRequest<{ tenant_id: string; analysis_task: WeeklyLearningTask }>("/api/reports/weekly-version/analyze", {
    method: "POST",
    context: { tenantId, userId },
    body: { version_id: versionId, force },
  });
}
