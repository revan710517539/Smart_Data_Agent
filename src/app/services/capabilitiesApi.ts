import { apiRequest } from "./apiClient";
import { getDefaultUserId } from "./apiContext";

export type PlatformCapabilityResponse = {
  agents: Array<{ agent_id: string; name: string; type: string; status: string; allowed_skills: string[] }>;
  agent_groups: Array<{ group_id: string; name: string; controller_agent: string; stage_gates: string[]; agent_ids: string[] }>;
  skills: Array<{
    skill_id: string;
    version: string;
    configured: boolean;
    implemented: boolean;
    healthy: boolean;
    enabled: boolean;
    status: string;
  }>;
  mcp_servers: Array<Record<string, unknown>>;
};

export async function fetchPlatformCapabilities({ tenantId, userId = getDefaultUserId() }: { tenantId: string; userId?: string }) {
  return apiRequest<PlatformCapabilityResponse>("/api/platform/capabilities", {
    method: "GET",
    context: { tenantId, userId },
  });
}
