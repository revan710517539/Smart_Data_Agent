import { apiRequest } from "./apiClient";
import { getDefaultUserId } from "./apiContext";

export type NavigationItem = {
  key: string;
  label: string;
  children: NavigationItem[];
};

export type NavigationResponse = {
  tenant_id: string;
  user_id: string;
  menu_keys: string[];
  menu_tree: NavigationItem[];
};

export async function fetchNavigation({
  tenantId,
  userId = getDefaultUserId(),
}: {
  tenantId: string;
  userId?: string;
}): Promise<NavigationResponse> {
  return apiRequest<NavigationResponse>("/api/navigation", {
    method: "GET",
    context: { tenantId, userId },
    readCache: { ttlMs: 10_000, tags: ["navigation"] },
  });
}
