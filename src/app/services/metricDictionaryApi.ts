import type { MetricDictionaryItem } from "../data/metricDictionary";
import { apiRequest } from "./apiClient";
import { getDefaultUserId } from "./apiContext";

type MetricDictionaryParams = {
  tenantId: string;
  userId?: string;
};

type MetricDictionaryResponse = {
  tenant_id: string;
  metrics: MetricDictionaryItem[];
  count: number;
};

export async function fetchMetricDictionary({
  tenantId,
  userId = getDefaultUserId(),
}: MetricDictionaryParams): Promise<MetricDictionaryResponse> {
  return apiRequest<MetricDictionaryResponse>("/api/metric-dictionary", {
    method: "GET",
    context: { tenantId, userId },
    readCache: { ttlMs: 30_000, tags: ["metric-dictionary"] },
  });
}

export async function replaceMetricDictionary({
  tenantId,
  userId = getDefaultUserId(),
  metrics,
}: MetricDictionaryParams & { metrics: MetricDictionaryItem[] }): Promise<MetricDictionaryResponse> {
  return apiRequest<MetricDictionaryResponse>("/api/metric-dictionary", {
    method: "PUT",
    context: { tenantId, userId },
    body: { metrics },
    timeoutMs: 20000,
  });
}

export async function saveMetricDictionaryItem({
  tenantId,
  userId = getDefaultUserId(),
  metric,
}: MetricDictionaryParams & { metric: MetricDictionaryItem }): Promise<{ tenant_id: string; metric: MetricDictionaryItem }> {
  return apiRequest<{ tenant_id: string; metric: MetricDictionaryItem }>("/api/metric-dictionary", {
    method: "POST",
    context: { tenantId, userId },
    body: { metric },
  });
}

export type MetricDictionaryImportResult = {
  tenant_id: string;
  created: MetricDictionaryItem[];
  created_count: number;
  skipped_count: number;
  skipped_names: string[];
};

export async function importMetricDictionaryWorkbook({
  tenantId,
  userId = getDefaultUserId(),
  file,
}: MetricDictionaryParams & { file: File }): Promise<MetricDictionaryImportResult> {
  const fileContentBase64 = await fileToBase64(file);
  return apiRequest<MetricDictionaryImportResult>("/api/metric-dictionary/import", {
    method: "POST",
    context: { tenantId, userId },
    body: { file_name: file.name, file_content_base64: fileContentBase64 },
    // Workbooks can be several thousand rows and a single server transaction.
    timeoutMs: 60_000,
  });
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("指标文件读取失败，请重新选择。"));
    reader.onload = () => {
      const value = String(reader.result || "");
      resolve(value.includes(",") ? value.split(",", 2)[1] : value);
    };
    reader.readAsDataURL(file);
  });
}

export async function deleteMetricDictionaryItem({
  tenantId,
  userId = getDefaultUserId(),
  metricId,
}: MetricDictionaryParams & { metricId: string }): Promise<{ tenant_id: string; metric_id: string; deleted: boolean }> {
  const params = new URLSearchParams({ metric_id: metricId });
  return apiRequest<{ tenant_id: string; metric_id: string; deleted: boolean }>(
    `/api/metric-dictionary?${params.toString()}`,
    {
      method: "DELETE",
      context: { tenantId, userId },
    },
  );
}

export type MetricSemanticVersion = {
  version_id: string;
  metric_key: string;
  version_no: number;
  status: "draft" | "review" | "published" | "superseded" | "rejected" | "archived";
  definition: Record<string, unknown>;
  checksum: string;
  parent_version_id?: string | null;
  submitted_by?: string | null;
  reviewed_by?: string | null;
  review_comment?: string;
  created_at: string;
};

export async function fetchMetricVersions({ tenantId, userId = getDefaultUserId(), metricId }: MetricDictionaryParams & { metricId: string }) {
  const query = new URLSearchParams({ metric_key: metricId });
  return apiRequest<{ metric_key: string; versions: MetricSemanticVersion[]; count: number }>(`/api/semantic/metric-versions?${query}`, { context: { tenantId, userId } });
}

export async function fetchMetricVersionImpact({ tenantId, userId = getDefaultUserId(), metricId }: MetricDictionaryParams & { metricId: string }) {
  const query = new URLSearchParams({ metric_key: metricId });
  return apiRequest<{ metric_key: string; reports: string[]; skills: string[]; analysis_tasks: string[]; cache_entries: string[]; impact_count: number }>(`/api/semantic/metric-versions/impact?${query}`, { context: { tenantId, userId } });
}

export type MetricVersionDiff = {
  left_version_id: string;
  right_version_id: string;
  changed_fields: Array<{ field: string; before: unknown; after: unknown }>;
  changed_count: number;
};

export async function fetchMetricVersionDiff({ tenantId, userId = getDefaultUserId(), metricId, leftVersionId, rightVersionId }: MetricDictionaryParams & { metricId: string; leftVersionId: string; rightVersionId: string }) {
  const query = new URLSearchParams({ metric_key: metricId, left_version_id: leftVersionId, right_version_id: rightVersionId });
  return apiRequest<MetricVersionDiff>(`/api/semantic/metric-versions/diff?${query}`, { context: { tenantId, userId } });
}

export async function createMetricVersion({ tenantId, userId = getDefaultUserId(), metricId, definition, parentVersionId }: MetricDictionaryParams & { metricId: string; definition: Record<string, unknown>; parentVersionId?: string }) {
  return apiRequest<{ version: MetricSemanticVersion }>("/api/semantic/metric-versions", { method: "POST", context: { tenantId, userId }, body: { metric_key: metricId, definition, parent_version_id: parentVersionId } });
}

export async function transitionMetricVersion({ tenantId, userId = getDefaultUserId(), versionId, action, comment = "" }: MetricDictionaryParams & { versionId: string; action: "submit" | "publish" | "reject" | "archive"; comment?: string }) {
  return apiRequest<{ version: MetricSemanticVersion }>("/api/semantic/metric-versions/transition", { method: "POST", context: { tenantId, userId }, body: { version_id: versionId, action, comment } });
}

export async function rollbackMetricVersion({ tenantId, userId = getDefaultUserId(), metricId, versionId }: MetricDictionaryParams & { metricId: string; versionId: string }) {
  return apiRequest<{ version: MetricSemanticVersion }>("/api/semantic/metric-versions/rollback", { method: "POST", context: { tenantId, userId }, body: { metric_key: metricId, version_id: versionId } });
}
