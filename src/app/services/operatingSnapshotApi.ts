import { apiRequest } from "./apiClient";
import { getDefaultTenantId, getDefaultUserId } from "./apiContext";

export type SnapshotDataset = {
  status: "ready" | "unavailable";
  rows: Record<string, unknown>[];
  error_code?: string;
  query?: { sql_hash: string; parameters: Record<string, unknown>; row_count: number };
  evidence: {
    evidence_id?: string;
    data_source?: string;
    data_mode: "real" | "mock" | "unavailable";
    publishable: boolean;
    source_snapshot?: Record<string, unknown>;
    aggregation_semantics_complete?: boolean;
    policy_enforced_at_source?: boolean;
  };
};

export type OperatingSnapshot = {
  tenant_id: string;
  view: string;
  status: "ready" | "partial" | "unavailable";
  data_modes: string[];
  publishable: boolean;
  datasets: Record<string, SnapshotDataset>;
  generated_at: string;
};

export function fetchOperatingSnapshot({
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
  view,
  filters = {},
}: {
  tenantId?: string;
  userId?: string;
  view: "dashboard" | "business_funnel" | "customer_insight" | "institution_supervision" | "weekly_report";
  filters?: Record<string, string>;
}) {
  const params = new URLSearchParams({ view });
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  return apiRequest<OperatingSnapshot>(`/api/operating-snapshot?${params.toString()}`, {
    method: "GET",
    context: { tenantId, userId },
  });
}
