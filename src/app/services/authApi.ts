import type { AccessUser } from "./accessControlApi";
import { apiRequest, getApiBaseUrl } from "./apiClient";

export type AuthSession = {
  token?: string;
  user: AccessUser;
  tenant_id: string;
  institution: string;
  institutions: string[];
  tenant_directory?: Array<{ id: string; name: string }>;
  is_super_admin: boolean;
  session_expires_at?: number;
  session_idle_expires_at?: number;
  session_absolute_expires_at?: number;
  survey_submission?: { message_id: string; status: "new"; verified: boolean };
};

export type LoginSurveyAnswers = {
  messageId: string;
  neededMetrics: string;
  reportUsage: string;
  trigger: LoginSurveyTrigger;
};

export type LoginSurveyTrigger = "login" | "cancel" | "pagehide";

export type LoginSurveyDraft = LoginSurveyAnswers & {
  account: string;
  institution: string;
};

export async function loginWithEmail({
  email,
  password,
  institution,
  survey,
}: {
  email: string;
  password: string;
  institution?: string;
  survey?: LoginSurveyAnswers;
}) {
  return apiRequest<AuthSession>("/api/auth/login", {
    method: "POST",
    body: {
      email,
      password,
      institution,
      ...(survey
        ? {
            survey: {
              message_id: survey.messageId,
              needed_metrics: survey.neededMetrics,
              report_usage: survey.reportUsage,
              trigger: survey.trigger,
            },
          }
        : {}),
    },
  });
}

export async function submitLoginSurveyDraft(draft: LoginSurveyDraft) {
  return apiRequest<{
    status: "saved" | "ignored_empty";
    survey_submission: { message_id: string; status: "new"; verified: false } | null;
  }>("/api/auth/login-survey", {
    method: "POST",
    keepalive: true,
    body: loginSurveyDraftPayload(draft),
  });
}

export function sendLoginSurveyBeacon(draft: LoginSurveyDraft) {
  if (typeof navigator.sendBeacon !== "function") return false;
  return navigator.sendBeacon(
    `${getApiBaseUrl()}/api/auth/login-survey`,
    new Blob([JSON.stringify(loginSurveyDraftPayload(draft))], { type: "text/plain;charset=UTF-8" }),
  );
}

function loginSurveyDraftPayload(draft: LoginSurveyDraft) {
  return {
    account: draft.account,
    institution: draft.institution,
    survey: {
      message_id: draft.messageId,
      needed_metrics: draft.neededMetrics,
      report_usage: draft.reportUsage,
      trigger: draft.trigger,
    },
  };
}

export async function logoutSession() {
  return apiRequest<{ status: "logged_out" }>("/api/auth/logout", { method: "POST" });
}

export async function fetchCurrentSession() {
  return apiRequest<AuthSession>("/api/auth/me", { method: "GET" });
}

export async function beginEnterpriseLogin() {
  return apiRequest<{ authorization_url: string; expires_at: number }>("/api/auth/oidc/start", { method: "GET" });
}

export type RegistrationRequestResult = {
  status: "pending_approval";
  request_id: string;
  institution: string;
  tenant_id: string;
  contact: string;
  name: string;
  role: string;
  message: string;
};

export async function changeAccountPassword({
  currentPassword,
  newPassword,
}: {
  currentPassword: string;
  newPassword: string;
}) {
  return apiRequest<{ status: "password_changed" }>("/api/auth/password", {
    method: "POST",
    body: { current_password: currentPassword, new_password: newPassword },
  });
}

export async function registerWithEmail({
  name,
  email,
  phone,
  password,
  institution,
}: {
  name?: string;
  email?: string;
  phone?: string;
  password: string;
  institution: string;
}) {
  return apiRequest<RegistrationRequestResult>("/api/auth/register", {
    method: "POST",
    body: { name, email, phone, password, institution },
  });
}
