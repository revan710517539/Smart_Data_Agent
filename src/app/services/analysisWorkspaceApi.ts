import { apiRequest } from "./apiClient";
import type { ApiContextParams } from "./apiContext";

export type AnalysisAction = "follow_up" | "branch" | "merge" | "trust" | "freeze_report" | "rerun";

export type DatasetSnapshot = {
  id?: string;
  version?: string;
  sha256?: string;
  generatedAt?: string;
};

export type MetricVersionRef = {
  metricId: string;
  version: string;
};

export type SelectedDataPoint = {
  targetType: "chart" | "table" | "metric" | "institution" | "text";
  targetId: string;
  label?: string;
  values?: Record<string, unknown>;
};

export type EvidenceRef = {
  id: string;
  type?: string;
  label?: string;
};

export type AnalysisWorkspaceContext = {
  pageKey: string;
  artifactId: string;
  datasetSnapshot: DatasetSnapshot;
  metricVersions: MetricVersionRef[];
  filters: Record<string, unknown>;
  selectedDataPoint?: SelectedDataPoint;
  allowedActions: AnalysisAction[];
  evidenceRefs: EvidenceRef[];
};

export type AnalysisTurn = {
  turn_id: string;
  thread_id: string;
  turn_no: number;
  question: string;
  answer: string;
  status: "clarification" | "queued" | "running" | "completed" | "partial" | "failed" | "cancelled";
  intent: Record<string, unknown>;
  execution_plan: Record<string, unknown>;
  artifact_refs: Array<Record<string, unknown>>;
  evidence_refs: Array<Record<string, unknown>>;
};

export type AnalysisThread = {
  thread_id: string;
  workspace_id: string;
  parent_thread_id: string | null;
  root_thread_id: string;
  title: string;
  anchor: Record<string, unknown>;
  status: "active" | "merged" | "archived";
  turns: AnalysisTurn[];
};

export type AnalysisWorkspace = {
  workspace_id: string;
  workspace_key: string;
  page_key: string;
  artifact_ref: string;
  status: string;
};

export async function ensureAnalysisWorkspace(
  workspaceKey: string,
  workspaceContext: AnalysisWorkspaceContext,
  context: ApiContextParams,
) {
  return apiRequest<{ workspace: AnalysisWorkspace }>("/api/analysis/workspaces", {
    method: "POST",
    context,
    body: {
      workspace_key: workspaceKey,
      context: {
        page_key: workspaceContext.pageKey,
        artifact_id: workspaceContext.artifactId,
        dataset_snapshot: workspaceContext.datasetSnapshot,
        metric_versions: workspaceContext.metricVersions,
        filters: workspaceContext.filters,
        selected_data_point: workspaceContext.selectedDataPoint,
        allowed_actions: workspaceContext.allowedActions,
        evidence_refs: workspaceContext.evidenceRefs,
      },
    },
  });
}

export async function fetchAnalysisWorkspace(workspaceId: string, context: ApiContextParams) {
  const query = new URLSearchParams({ workspace_id: workspaceId });
  return apiRequest<{ workspace: AnalysisWorkspace; threads: AnalysisThread[] }>(`/api/analysis/workspaces?${query}`, { context });
}

export async function createAnalysisBranch(
  workspaceId: string,
  parentThreadId: string | null,
  title: string,
  anchor: Record<string, unknown>,
  context: ApiContextParams,
) {
  return apiRequest<{ thread: AnalysisThread }>("/api/analysis/threads/branches", {
    method: "POST",
    context,
    body: { workspace_id: workspaceId, parent_thread_id: parentThreadId, title, anchor },
  });
}

export async function appendAnalysisTurn(
  threadId: string,
  payload: Pick<AnalysisTurn, "question" | "answer" | "status"> & Partial<Pick<AnalysisTurn, "intent" | "execution_plan" | "artifact_refs" | "evidence_refs">>,
  context: ApiContextParams,
) {
  return apiRequest<{ turn: AnalysisTurn }>("/api/analysis/threads/turns", {
    method: "POST",
    context,
    body: { thread_id: threadId, ...payload },
  });
}

export async function mergeAnalysisThreads(
  targetThreadId: string,
  sourceThreadIds: string[],
  question: string,
  answer: string,
  evidenceRefs: Array<Record<string, unknown>>,
  context: ApiContextParams,
) {
  return apiRequest<{ turn: AnalysisTurn }>("/api/analysis/threads/merge", {
    method: "POST",
    context,
    body: { target_thread_id: targetThreadId, source_thread_ids: sourceThreadIds, question, answer, evidence_refs: evidenceRefs },
  });
}

export async function runWorkspaceAnalysis(question: string, pageContext: Record<string, unknown>, context: ApiContextParams) {
  return apiRequest<Record<string, unknown>>("/api/analysis/run", {
    method: "POST",
    context,
    timeoutMs: 120_000,
    body: { question, page_context: pageContext },
  });
}

export type TrustedArtifactManifest = {
  manifest_version: number;
  tenant_id: string;
  artifact_id: string;
  dataset_snapshot: Record<string, unknown>;
  metric_versions: Array<Record<string, unknown>>;
  sql_hash: string;
  result_hash: string;
  visualization_hash: string;
  skill_versions: Array<Record<string, unknown>>;
  model_version: string;
  authorization_hash: string;
  evidence_refs: Array<Record<string, unknown>>;
  evaluation: Record<string, unknown>;
  created_at: string;
  manifest_hash: string;
};

export async function fetchTrustedArtifactManifest(taskId: string, context: ApiContextParams) {
  const query = new URLSearchParams({ task_id: taskId });
  return apiRequest<{ manifest: TrustedArtifactManifest }>(`/api/analysis/artifacts/trust?${query}`, { context });
}

export type MetricSemanticVersion = {
  version_id: string;
  metric_key: string;
  version_no: number;
  status: "draft" | "review" | "published" | "superseded" | "rejected" | "archived";
  definition: Record<string, unknown>;
  review_comment: string;
};

export async function fetchMetricVersions(metricKey: string, context: ApiContextParams) {
  const query = new URLSearchParams({ metric_key: metricKey });
  return apiRequest<{ versions: MetricSemanticVersion[] }>(`/api/semantic/metric-versions?${query}`, { context });
}

export async function fetchMetricVersionImpact(metricKey: string, context: ApiContextParams) {
  const query = new URLSearchParams({ metric_key: metricKey });
  return apiRequest<{ impact_count: number; reports: string[]; skills: string[]; analysis_tasks: string[]; cache_entries: string[] }>(`/api/semantic/metric-versions/impact?${query}`, { context });
}
