type ApiContextParams = {
  tenantId?: string;
  userId?: string;
};

const authSessionStorageKey = "smart_data_agent_auth_session_v1";
const defaultUserId = (import.meta.env.VITE_SMART_DATA_AGENT_USER_ID || "u_super_admin").trim();
const defaultTenantId = (import.meta.env.VITE_SMART_DATA_AGENT_TENANT_ID || "tenant_demo").trim();
const accessManagerUserId = (import.meta.env.VITE_SMART_DATA_AGENT_ACCESS_USER_ID || defaultUserId).trim();

export type { ApiContextParams };

export function getDefaultUserId() {
  return getStoredSessionContext().userId || defaultUserId;
}

export function getDefaultTenantId() {
  return getStoredSessionContext().tenantId || defaultTenantId;
}

export function getAccessManagerUserId() {
  return getStoredSessionContext().userId || accessManagerUserId;
}

export function hasStoredAuthSession() {
  const session = getStoredSessionContext();
  return Boolean(session.userId && session.tenantId);
}

export function isDemoFallbackEnabled() {
  return (import.meta.env.VITE_SMART_DATA_AGENT_ENABLE_DEMO_FALLBACK || "").trim().toLowerCase() === "true";
}

export function demoFallbackDisabledMessage(action: string) {
  return `${action}失败。当前未开启前端 demo fallback，避免把本地缓存误当作企业级数据。`;
}

export function apiContextHeaders({ tenantId, userId }: ApiContextParams = {}) {
  const storedContext = getStoredSessionContext();
  const resolvedUserId = userId || storedContext.userId || defaultUserId;
  const resolvedTenantId = tenantId || storedContext.tenantId || defaultTenantId;
  const token = (import.meta.env.VITE_SMART_DATA_AGENT_AUTH_TOKEN || "").trim();
  if (token) {
    return {
      Authorization: `Bearer ${token}`,
      "X-Tenant-Id": encodeURIComponent(resolvedTenantId),
    };
  }
  const developmentIdentityHeaders =
    (import.meta.env.VITE_SMART_DATA_AGENT_ENABLE_DEV_IDENTITY_HEADERS || "").trim().toLowerCase() === "true";
  return developmentIdentityHeaders
    ? {
        "X-User-Id": resolvedUserId,
        "X-Tenant-Id": encodeURIComponent(resolvedTenantId),
      }
    : { "X-Tenant-Id": encodeURIComponent(resolvedTenantId) };
}

function getStoredSessionContext(): { userId?: string; tenantId?: string } {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(authSessionStorageKey);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as { user?: { id?: string }; tenant_id?: string };
    return {
      userId: String(parsed.user?.id || "").trim(),
      tenantId: String(parsed.tenant_id || "").trim(),
    };
  } catch {
    return {};
  }
}
