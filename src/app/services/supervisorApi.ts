import { apiRequest } from "./apiClient";
import { getDefaultUserId } from "./apiContext";

export type SupervisorChatMessage = {
  role: "user" | "agent" | "system";
  content: string;
};

export type SupervisorChatResponse = {
  tenant_id: string;
  status: string;
  reply: string;
  error_code?: string;
  used_model?: string;
  model_id?: string;
};

export async function chatWithAgentSupervisor({
  tenantId,
  userId = getDefaultUserId(),
  question,
  pagePath,
  institution,
  conversation,
  modelApplicationSelection,
}: {
  tenantId: string;
  userId?: string;
  question: string;
  pagePath: string;
  institution: string;
  conversation: SupervisorChatMessage[];
  modelApplicationSelection?: { integrationId: string; selectedModelName: string } | null;
}): Promise<SupervisorChatResponse> {
  return apiRequest<SupervisorChatResponse>("/api/agent-supervisor/chat", {
    method: "POST",
    context: { tenantId, userId },
    body: {
      question,
      page_path: pagePath,
      institution,
      conversation: conversation.slice(-8).map((item) => ({ role: item.role, content: item.content })),
      model_application_selection: modelApplicationSelection || undefined,
    },
    timeoutMs: 60_000,
  });
}
