import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  institutionNameFromTenant,
  operatingTenantNames,
  tenantIdFromInstitution,
} from "../data/operatingTenants";
import { getAccessManagerUserId, getDefaultUserId } from "../services/apiContext";
import { fetchTenants } from "../services/tenantApi";
import type { AccessTenantRole, AccessUser } from "../services/accessControlApi";
import type { AuthSession } from "../services/authApi";
import { fetchCurrentSession, logoutSession } from "../services/authApi";
import { sessionRevalidationEvent } from "../services/apiClient";
import { resetTransientUiStateForNewAuthSession } from "./sessionUiState";

export const authSessionStorageKey = "smart_data_agent_auth_session_v1";
export const selectedInstitutionStorageKey = "smart_data_agent_selected_institution_v1";
const globalInstitutionScopeLabel = "全部机构";

type PlatformContextValue = {
  accessManagerUserId: string;
  authSession: AuthSession | null;
  currentUser: AccessUser | null;
  currentTenantRoles: AccessTenantRole[];
  institutions: string[];
  isAuthenticated: boolean;
  isInstitutionAdmin: boolean;
  isSuperAdmin: boolean;
  login: (session: AuthSession) => void;
  logout: () => void;
  selectedInstitution: string;
  setSelectedInstitution: (institution: string) => void;
  tenantId: string;
  tenantIdForInstitution: (institution: string) => string;
  userId: string;
  userName: string;
};

const PlatformContext = createContext<PlatformContextValue | null>(null);

export function PlatformProvider({ children }: { children: ReactNode }) {
  const [authSession, setAuthSession] = useState<AuthSession | null>(() => loadStoredSession());
  // Render the cached authenticated shell immediately. Session validation still
  // runs in the background, but it must not create a blank first screen before
  // the local API responds.
  const [isSessionResolved, setIsSessionResolved] = useState(true);
  const [tenantCatalog, setTenantCatalog] = useState<string[]>(operatingTenantNames);
  const [tenantCatalogStatus, setTenantCatalogStatus] = useState<"loading" | "ready" | "unavailable">("loading");
  const [tenantIdByInstitution, setTenantIdByInstitution] = useState<Record<string, string>>(() =>
    Object.fromEntries(operatingTenantNames.map((name) => [name, tenantIdFromInstitution(name)])),
  );
  const [selectedInstitution, setSelectedInstitutionState] = useState(() => resolveInitialInstitution(authSession));
  const sessionMutationVersion = useRef(0);
  const sessionSyncPromise = useRef<Promise<void> | null>(null);
  const hasGlobalTenantAccess = Boolean(
    authSession && sessionHasGlobalTenantAccess(authSession),
  );
  const authorizedInstitutions = normalizeSelectableInstitutions(authSession?.institutions || []);
  const institutions = hasGlobalTenantAccess
    ? tenantCatalogStatus === "ready" || !authorizedInstitutions.length
      ? tenantCatalog
      : authorizedInstitutions
    : authSession
      ? authorizedInstitutions
      : tenantCatalog;

  useEffect(() => {
    let cancelled = false;
    const loadTenants = async () => {
      try {
        const response = await fetchTenants();
        const names = normalizeSelectableInstitutions(response.tenants
          .filter((tenant) => tenant.status === "active")
          .map((tenant) => tenant.name || tenant.id));
        if (!cancelled && names.length) {
          setTenantCatalog(names);
          setTenantIdByInstitution(buildTenantIdCatalog(response.tenants));
          setTenantCatalogStatus("ready");
        } else if (!cancelled) {
          setTenantCatalogStatus("unavailable");
        }
      } catch {
        if (!cancelled) {
          setTenantCatalogStatus("unavailable");
        }
      }
    };
    void loadTenants();
    return () => {
      cancelled = true;
    };
  }, []);

  const syncCurrentSession = useCallback(() => {
    if (sessionSyncPromise.current) return sessionSyncPromise.current;
    const mutationVersion = sessionMutationVersion.current;
    const cachedSession = loadStoredSession();
    // A signed cookie alone is not enough evidence that this browser started a
    // session in this app. Avoid probing protected endpoints on the login page.
    if (!cachedSession) {
      setIsSessionResolved(true);
      return Promise.resolve();
    }
    const hadCachedSession = true;
    const pending = fetchCurrentSession()
      .then((current) => {
        if (mutationVersion !== sessionMutationVersion.current) return;
        const normalized = normalizeAuthSession(current);
        const selected = readStoredSelectedInstitution(normalized) || resolveSessionInstitution(normalized);
        const selectedSession = {
          ...normalized,
          institution: selected,
          tenant_id: tenantIdFromInstitution(selected),
        };
        setAuthSession(selectedSession);
        setSelectedInstitutionState(selected);
        window.localStorage.setItem(selectedInstitutionStorageKey, selected);
        window.localStorage.setItem(authSessionStorageKey, JSON.stringify(selectedSession));
      })
      .catch((error) => {
        if (mutationVersion !== sessionMutationVersion.current) return;
        // A transient backend/network failure must not log out an otherwise
        // valid cached session. Only a confirmed authentication rejection can
        // invalidate it; backend authorization remains the final gate.
        if (hadCachedSession && (!(error instanceof Error) || !("status" in error) || error.status !== 401)) return;
        setAuthSession(null);
        setSelectedInstitutionState(operatingTenantNames[0]);
        window.localStorage.removeItem(selectedInstitutionStorageKey);
        window.localStorage.removeItem(authSessionStorageKey);
      })
      .finally(() => {
        if (sessionSyncPromise.current === pending) sessionSyncPromise.current = null;
        setIsSessionResolved(true);
      });
    sessionSyncPromise.current = pending;
    return pending;
  }, []);

  useEffect(() => {
    void syncCurrentSession();
    const revalidate = () => void syncCurrentSession();
    const revalidateVisibleSession = () => {
      if (document.visibilityState === "visible") revalidate();
    };
    window.addEventListener("focus", revalidate);
    window.addEventListener(sessionRevalidationEvent, revalidate);
    document.addEventListener("visibilitychange", revalidateVisibleSession);
    return () => {
      window.removeEventListener("focus", revalidate);
      window.removeEventListener(sessionRevalidationEvent, revalidate);
      document.removeEventListener("visibilitychange", revalidateVisibleSession);
    };
  }, [syncCurrentSession]);

  const setSelectedInstitution = useCallback(
    (institution: string) => {
      const target = normalizeSelectableInstitution(institution) || institutions[0] || operatingTenantNames[0];
      if (institutions.length && !institutions.includes(target)) return;
      setSelectedInstitutionState(target);
      window.localStorage.setItem(selectedInstitutionStorageKey, target);
      if (!authSession) return;
      const nextInstitutions = hasGlobalTenantAccess
        ? Array.from(new Set([...authSession.institutions, ...tenantCatalog, target]))
        : authSession.institutions;
      const nextSession: AuthSession = {
        ...authSession,
        institutions: nextInstitutions,
        institution: target,
        tenant_id: resolveTenantIdForInstitution(target, authSession, tenantIdByInstitution),
      };
      setAuthSession(nextSession);
      window.localStorage.setItem(authSessionStorageKey, JSON.stringify(nextSession));
    },
    [authSession, hasGlobalTenantAccess, institutions, tenantCatalog, tenantIdByInstitution],
  );

  useEffect(() => {
    if (!authSession) return;
    if (!institutions.includes(selectedInstitution)) {
      setSelectedInstitution(institutions[0] || operatingTenantNames[0]);
    }
  }, [authSession, institutions, selectedInstitution, setSelectedInstitution]);

  const login = (session: AuthSession) => {
    sessionMutationVersion.current += 1;
    resetTransientUiStateForNewAuthSession();
    const normalizedInputSession = normalizeAuthSession(session);
    const selected = resolveSessionInstitution(normalizedInputSession);
    const nextSession = {
      ...normalizedInputSession,
      institution: selected,
      tenant_id: tenantIdFromInstitution(selected),
    };
    setAuthSession(nextSession);
    setIsSessionResolved(true);
    setSelectedInstitutionState(selected);
    window.localStorage.setItem(selectedInstitutionStorageKey, selected);
    window.localStorage.setItem(authSessionStorageKey, JSON.stringify(nextSession));
  };

  const logout = () => {
    sessionMutationVersion.current += 1;
    resetTransientUiStateForNewAuthSession();
    void logoutSession().catch(() => undefined);
    setAuthSession(null);
    setSelectedInstitutionState(operatingTenantNames[0]);
    window.localStorage.removeItem(selectedInstitutionStorageKey);
    window.localStorage.removeItem(authSessionStorageKey);
  };

  const currentTenantRoles = authSession
    ? authSession.user.tenantRoles.filter((role) => role.tenant === "全部机构" || role.tenant === selectedInstitution)
    : [];
  const isSuperAdmin = Boolean(hasGlobalTenantAccess || currentTenantRoles.some((role) => role.role === "超级管理员"));
  const isInstitutionAdmin = Boolean(isSuperAdmin || currentTenantRoles.some((role) => role.role === "管理员"));
  const tenantIdForInstitution = useCallback(
    (institution: string) => resolveTenantIdForInstitution(institution, authSession, tenantIdByInstitution),
    [authSession, tenantIdByInstitution],
  );

  const value = useMemo<PlatformContextValue>(
    () => ({
      accessManagerUserId: authSession?.user.id || getAccessManagerUserId(),
      authSession,
      currentUser: authSession?.user || null,
      currentTenantRoles,
      institutions,
      isAuthenticated: Boolean(authSession),
      isInstitutionAdmin,
      isSuperAdmin,
      login,
      logout,
      selectedInstitution,
      setSelectedInstitution,
      tenantId: resolveTenantIdForInstitution(selectedInstitution, authSession, tenantIdByInstitution),
      tenantIdForInstitution,
      userId: authSession?.user.id || getDefaultUserId(),
      userName: authSession?.user.name || "未登录",
    }),
    [authSession, currentTenantRoles, institutions, isInstitutionAdmin, isSuperAdmin, selectedInstitution, setSelectedInstitution, tenantIdByInstitution, tenantIdForInstitution],
  );

  return (
    <PlatformContext.Provider value={value}>
      {isSessionResolved ? children : <SessionRestoreScreen />}
    </PlatformContext.Provider>
  );
}

export function usePlatformContext() {
  const context = useContext(PlatformContext);
  if (!context) {
    throw new Error("usePlatformContext must be used inside PlatformProvider.");
  }
  return context;
}

function loadStoredSession(): AuthSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(authSessionStorageKey);
    if (!raw) return null;
    const session = normalizeAuthSession(JSON.parse(raw) as AuthSession);
    if (!session.user?.id || !session.institutions?.length) return null;
    const storedInstitution = readStoredSelectedInstitution(session);
    const institution = storedInstitution || session.institution || session.institutions[0];
    const normalizedSession = {
      ...session,
      institution,
      tenant_id: resolveTenantIdForInstitution(institution, session),
    };
    // Keep request context safe while the HttpOnly session is being verified.
    // The selected-institution cache is intentionally left untouched so the
    // verified response can decide whether that selection is still authorized.
    window.localStorage.setItem(authSessionStorageKey, JSON.stringify(normalizedSession));
    return normalizedSession;
  } catch {
    return null;
  }
}

function resolveInitialInstitution(session: AuthSession | null) {
  return readStoredSelectedInstitution(session) || resolveSessionInstitution(session);
}

function readStoredSelectedInstitution(session: AuthSession | null) {
  if (typeof window === "undefined") return "";
  const stored = normalizeSelectableInstitution(
    window.localStorage.getItem(selectedInstitutionStorageKey)?.trim() || "",
  );
  if (!stored) return "";
  if (!session) return operatingTenantNames.includes(stored as (typeof operatingTenantNames)[number]) ? stored : "";
  if (sessionHasGlobalTenantAccess(session)) {
    return session.institutions.includes(stored) || operatingTenantNames.includes(stored as (typeof operatingTenantNames)[number])
      ? stored
      : "";
  }
  return session.institutions.includes(stored) ? stored : "";
}

function sessionHasGlobalTenantAccess(session: AuthSession) {
  return Boolean(
    session.is_super_admin ||
      session.user.tenantRoles.some((role) => role.tenant === "全部机构" || role.role === "超级管理员"),
  );
}

function normalizeAuthSession(session: AuthSession): AuthSession {
  const { token: _discardedToken, ...safeSession } = session;
  const sessionInstitutions = normalizeSelectableInstitutions(safeSession.institutions || []);
  // “全部机构” is an authorization scope, never a selectable tenant. Older
  // cached super-admin sessions may contain only that scope label, so rebuild
  // their selector from the governed operating-tenant catalog.
  const institutions = sessionHasGlobalTenantAccess(safeSession) && !sessionInstitutions.length
    ? [...operatingTenantNames]
    : sessionInstitutions;
  const requestedInstitution = normalizeSelectableInstitution(safeSession.institution || safeSession.tenant_id || "");
  const institution = institutions.includes(requestedInstitution)
    ? requestedInstitution
    : institutions[0] || operatingTenantNames[0];
  return {
    ...safeSession,
    institution,
    institutions,
    tenant_id: resolveTenantIdForInstitution(institution, safeSession),
  };
}

function buildTenantIdCatalog(tenants: Array<{ id: string; name: string; status: string }>) {
  const catalog: Record<string, string> = {};
  for (const tenant of tenants) {
    if (tenant.status !== "active") continue;
    const tenantId = String(tenant.id || "").trim();
    const displayName = normalizeSelectableInstitution(tenant.name || tenantId);
    const codeLabel = normalizeSelectableInstitution(tenantId);
    if (!tenantId) continue;
    if (displayName) catalog[displayName] = tenantId;
    if (codeLabel) catalog[codeLabel] = tenantId;
  }
  return catalog;
}

function resolveTenantIdForInstitution(
  institution: string,
  session: AuthSession | null,
  catalog: Record<string, string> = {},
) {
  const normalized = normalizeSelectableInstitution(institution);
  const catalogTenantId = normalized ? catalog[normalized] : "";
  if (catalogTenantId) return catalogTenantId;
  if (session?.tenant_id) {
    const sessionInstitution = normalizeSelectableInstitution(session.institution || "");
    const sessionTenantLabel = normalizeSelectableInstitution(session.tenant_id);
    if (normalized && (normalized === sessionInstitution || normalized === sessionTenantLabel)) {
      return session.tenant_id;
    }
  }
  return tenantIdFromInstitution(institution);
}

function resolveSessionInstitution(session: AuthSession | null) {
  if (!session) return operatingTenantNames[0];
  const requested = normalizeSelectableInstitution(session.institution || session.tenant_id || "");
  return session.institutions.includes(requested)
    ? requested
    : session.institutions[0] || operatingTenantNames[0];
}

function normalizeSelectableInstitutions(values: string[]) {
  const normalized = Array.from(new Set(values.map(normalizeSelectableInstitution).filter(Boolean)));
  const catalogOrder = new Map(operatingTenantNames.map((name, index) => [name, index]));
  return normalized.sort((left, right) => {
    const leftOrder = catalogOrder.get(left as (typeof operatingTenantNames)[number]);
    const rightOrder = catalogOrder.get(right as (typeof operatingTenantNames)[number]);
    if (leftOrder !== undefined || rightOrder !== undefined) {
      return (leftOrder ?? Number.MAX_SAFE_INTEGER) - (rightOrder ?? Number.MAX_SAFE_INTEGER);
    }
    return left.localeCompare(right, "zh-CN");
  });
}

function normalizeSelectableInstitution(value: string) {
  const normalized = institutionNameFromTenant(String(value || ""));
  if (!normalized || normalized === globalInstitutionScopeLabel) return "";
  // Do not leak legacy/internal tenant placeholders into the institution UI.
  // Proper identifiers such as `tenant:华兴银行` have already been converted
  // to their display label by institutionNameFromTenant above.
  if (/^tenant(?:[_-].*)?$/i.test(normalized)) return "";
  return normalized;
}

function SessionRestoreScreen() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[#f8f8fa] text-[13px] text-[#8a8a8e]">
      正在恢复登录状态…
    </div>
  );
}
