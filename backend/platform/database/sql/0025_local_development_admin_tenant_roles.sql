-- The synthetic local-development identity can select any seeded operating
-- institution in the frontend. Keep its durable RBAC assignments aligned with
-- that local-only behavior so intelligent analysis does not fail after login
-- state falls back to u_admin. Production identities are unaffected.
INSERT OR IGNORE INTO auth_role_assignments(user_id, tenant_id, role_id, granted_by)
SELECT
    'u_admin',
    tenant_id,
    role_id,
    'u_super_admin'
FROM auth_roles
WHERE is_system = 1
  AND name = '管理员'
  AND tenant_id IS NOT NULL
  AND tenant_id <> 'tenant_demo';
