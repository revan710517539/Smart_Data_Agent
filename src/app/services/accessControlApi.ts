import { apiRequest } from "./apiClient";
import { getAccessManagerUserId } from "./apiContext";

export type AccessTenantRole = {
  tenant: string;
  /** Stable tenant code used by API/RBAC. `tenant` is only the display label. */
  tenantId?: string;
  role: string;
};

export type AccessUser = {
  id: string;
  name: string;
  department: string;
  status: string;
  lastLogin: string;
  email: string;
  tenantRoles: AccessTenantRole[];
};

export type AccessRole = {
  role_id: string;
  tenant_id: string | null;
  tenant: string;
  name: string;
  level: number;
  is_system: boolean;
  created_by?: string | null;
};

export type AccessRolePermission = {
  id: string;
  institution: string;
  adminMenus: string[];
  adminDataScopes: string[];
  operatorSuperMenus: string[];
  operatorSuperDataScopes: string[];
  operatorAdminMenus: string[];
  operatorAdminDataScopes: string[];
  manageableRoles: string[];
  customRoles: string[];
  roleConfigs?: AccessRoleConfig[];
  updatedBy: string;
  updatedAt: string;
};

export type AccessRoleConfig = {
  roleId: string;
  name: string;
  roleType: "admin" | "operator" | "custom";
  isSystem: boolean;
  menus: string[];
  dataScopes: string[];
  manageableRoles: string[];
};

type AccessParams = {
  tenantId: string;
  userId?: string;
};

type AccessUsersResponse = {
  tenant_id: string;
  users: AccessUser[];
  roles: AccessRole[];
  count: {
    users: number;
    roles: number;
  };
};

type AccessRolePoliciesResponse = {
  tenant_id: string;
  permissions: AccessRolePermission[];
  count: number;
};

export async function fetchAccessUsers({
  tenantId,
  userId = getAccessManagerUserId(),
}: AccessParams): Promise<AccessUsersResponse> {
  return apiRequest<AccessUsersResponse>("/api/access/users", {
    method: "GET",
    context: { tenantId, userId },
    readCache: { ttlMs: 8_000, tags: ["access-control"] },
  });
}

export async function saveAccessUser({
  tenantId,
  userId = getAccessManagerUserId(),
  user,
}: AccessParams & { user: AccessUser }): Promise<{ tenant_id: string; user: AccessUser }> {
  return apiRequest<{ tenant_id: string; user: AccessUser }>("/api/access/user", {
    method: "POST",
    context: { tenantId, userId },
    body: { user },
  });
}

export async function deleteAccessUser({
  tenantId,
  userId = getAccessManagerUserId(),
  targetUserId,
}: AccessParams & { targetUserId: string }): Promise<{ tenant_id: string; user_id: string; deleted: boolean }> {
  const params = new URLSearchParams({ target_user_id: targetUserId });
  return apiRequest<{ tenant_id: string; user_id: string; deleted: boolean }>(
    `/api/access/user?${params.toString()}`,
    {
      method: "DELETE",
      context: { tenantId, userId },
    },
  );
}

export async function fetchAccessRolePolicies({
  tenantId,
  userId = getAccessManagerUserId(),
}: AccessParams): Promise<AccessRolePoliciesResponse> {
  return apiRequest<AccessRolePoliciesResponse>("/api/access/role-policies", {
    method: "GET",
    context: { tenantId, userId },
    readCache: { ttlMs: 8_000, tags: ["access-control"] },
  });
}

export async function saveAccessRolePolicy({
  tenantId,
  userId = getAccessManagerUserId(),
  permission,
}: AccessParams & { permission: AccessRolePermission }): Promise<{ tenant_id: string; permission: AccessRolePermission }> {
  return apiRequest<{ tenant_id: string; permission: AccessRolePermission }>("/api/access/role-policy", {
    method: "POST",
    context: { tenantId, userId },
    body: { permission },
  });
}
