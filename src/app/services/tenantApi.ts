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

export type TenantMutationResponse = TenantsResponse & {
  tenant: TenantSummary;
  deleted?: boolean;
};

export async function fetchTenants(options?: { forceRefresh?: boolean }) {
  return apiRequest<TenantsResponse>("/api/tenants", {
    method: "GET",
    timeoutMs: 8000,
    readCache: { ttlMs: 60_000, tags: ["tenants"], forceRefresh: options?.forceRefresh },
  });
}

export async function createTenant(name: string) {
  return apiRequest<TenantMutationResponse>("/api/tenants", {
    method: "POST",
    body: { name },
  });
}

export async function updateTenant(id: string, name: string) {
  return apiRequest<TenantMutationResponse>("/api/tenants", {
    method: "PUT",
    body: { id, name },
  });
}

export async function deleteTenant(id: string) {
  const query = new URLSearchParams({ tenant_id: id });
  return apiRequest<TenantMutationResponse>(`/api/tenants?${query.toString()}`, {
    method: "DELETE",
  });
}
