import { apiRequest } from "./apiClient";

export type TenantSummary = {
  id: string;
  name: string;
  status: "active" | "inactive";
};

export type TenantsResponse = {
  tenants: TenantSummary[];
  count: number;
};

export async function fetchTenants() {
  return apiRequest<TenantsResponse>("/api/tenants", {
    method: "GET",
    timeoutMs: 8000,
  });
}
