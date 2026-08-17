import { apiRequest } from "./apiClient";

export type BridgeEnrollmentPreview = {
  channel: "workbuddy" | "codex" | "qwork";
  device_name: string;
  status: "pending" | "approved";
  expires_at: number;
};

export function fetchBridgeEnrollmentPreview(userCode: string) {
  return apiRequest<BridgeEnrollmentPreview>(
    `/api/integrations/bridge/enrollment/preview?user_code=${encodeURIComponent(userCode)}`,
  );
}

export function approveBridgeEnrollment(userCode: string) {
  return apiRequest<{ approved: true; channel: string; device_name: string; status: string }>(
    "/api/integrations/bridge/enrollment/approve",
    { method: "POST", body: { user_code: userCode } },
  );
}
