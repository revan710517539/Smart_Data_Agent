import { apiRequest } from "./apiClient";
import { getDefaultUserId } from "./apiContext";

export type AuditLog = {
  event_id: string;
  tenant_id: string;
  actor_user_id: string;
  actor_name: string;
  action: string;
  target_type: string;
  target_id: string;
  detail: Record<string, unknown>;
  ip_address: string;
  created_at: string;
};

type AuditLogsResponse = {
  tenant_id: string;
  logs: AuditLog[];
  count: number;
  total: number;
  limit: number;
  offset: number;
};

export function defaultAuditSince(now = new Date()) {
  return new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000).toISOString();
}

export async function fetchAuditLogs({
  tenantId,
  userId = getDefaultUserId(),
  limit = 20,
  offset = 0,
  since = defaultAuditSince(),
}: {
  tenantId: string;
  userId?: string;
  limit?: number;
  offset?: number;
  since?: string;
}): Promise<AuditLogsResponse> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset), since });
  return apiRequest<AuditLogsResponse>(`/api/audit-logs?${params.toString()}`, {
    method: "GET",
    context: { tenantId, userId },
    readCache: { ttlMs: 5_000, tags: ["audit-logs"] },
  });
}
