import type { AccessUser } from "./accessControlApi";
import { apiRequest } from "./apiClient";

export type AuthSession = {
  token?: string;
  user: AccessUser;
  tenant_id: string;
  institution: string;
  institutions: string[];
  is_super_admin: boolean;
  session_expires_at?: number;
  session_idle_expires_at?: number;
  session_absolute_expires_at?: number;
};

export async function loginWithEmail({
  email,
  institution,
}: {
  email: string;
  institution?: string;
}) {
  return apiRequest<AuthSession>("/api/auth/login", {
    method: "POST",
    body: { email, institution },
  });
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

export async function registerWithEmail({
  name,
  email,
  institution,
}: {
  name: string;
  email: string;
  institution: string;
}) {
  return apiRequest<AuthSession>("/api/auth/register", {
    method: "POST",
    body: { name, email, institution },
  });
}
