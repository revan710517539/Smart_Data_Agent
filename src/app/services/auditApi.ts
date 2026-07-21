import { apiRequest } from "./apiClient";
import { getDefaultUserId } from "./apiContext";

export type AuditLog = {
  event_id: string;
  tenant_id: string;
  actor_user_id: string;
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
};

export async function fetchAuditLogs({
  tenantId,
  userId = getDefaultUserId(),
  limit = 50,
}: {
  tenantId: string;
  userId?: string;
  limit?: number;
}): Promise<AuditLogsResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  return apiRequest<AuditLogsResponse>(`/api/audit-logs?${params.toString()}`, {
    method: "GET",
    context: { tenantId, userId },
  });
}
