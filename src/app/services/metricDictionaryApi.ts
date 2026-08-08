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
