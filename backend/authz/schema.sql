-- Native multi-tenant RBAC/ABAC schema.
-- PERM mapping:
--   r = auth request(user_id, tenant_id, resource_key, action, attrs)
--   p = auth_permissions + auth_role_permissions
--   g = auth_user_roles

CREATE TABLE auth_tenants (
  id BIGSERIAL PRIMARY KEY,
  tenant_code VARCHAR(64) NOT NULL UNIQUE,
  tenant_name VARCHAR(128) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  parent_id BIGINT REFERENCES auth_tenants(id),
  created_by BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE auth_users (
  id BIGSERIAL PRIMARY KEY,
  username VARCHAR(80) NOT NULL UNIQUE,
  display_name VARCHAR(80) NOT NULL,
  email VARCHAR(160),
  mobile VARCHAR(32),
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE auth_roles (
  id BIGSERIAL PRIMARY KEY,
  tenant_id BIGINT REFERENCES auth_tenants(id),
  role_key VARCHAR(80) NOT NULL,
  role_name VARCHAR(80) NOT NULL,
  role_level SMALLINT NOT NULL,
  is_system BOOLEAN NOT NULL DEFAULT false,
  created_by BIGINT REFERENCES auth_users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, role_key),
  CHECK (role_level IN (10, 50, 100)),
  CHECK (
    (role_level = 100 AND tenant_id IS NULL)
    OR (role_level <> 100 AND tenant_id IS NOT NULL)
  )
);

CREATE TABLE auth_resources (
  id BIGSERIAL PRIMARY KEY,
  resource_key VARCHAR(160) NOT NULL UNIQUE,
  resource_name VARCHAR(160) NOT NULL,
  resource_type VARCHAR(32) NOT NULL,
  parent_key VARCHAR(160),
  attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (resource_type IN ('menu', 'button', 'tenant', 'metric', 'role', 'skill', 'model', 'data_source'))
);

CREATE TABLE auth_permissions (
  id BIGSERIAL PRIMARY KEY,
  resource_key VARCHAR(160) NOT NULL REFERENCES auth_resources(resource_key),
  action VARCHAR(32) NOT NULL,
  effect VARCHAR(16) NOT NULL DEFAULT 'allow',
  conditions JSONB NOT NULL DEFAULT '{}'::jsonb,
  priority INTEGER NOT NULL DEFAULT 100,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (effect IN ('allow', 'deny'))
);

CREATE TABLE auth_user_roles (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES auth_users(id),
  tenant_id BIGINT REFERENCES auth_tenants(id),
  role_id BIGINT NOT NULL REFERENCES auth_roles(id),
  granted_by BIGINT REFERENCES auth_users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE auth_role_permissions (
  id BIGSERIAL PRIMARY KEY,
  role_id BIGINT NOT NULL REFERENCES auth_roles(id) ON DELETE CASCADE,
  permission_id BIGINT NOT NULL REFERENCES auth_permissions(id) ON DELETE CASCADE,
  granted_by BIGINT REFERENCES auth_users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (role_id, permission_id)
);

CREATE TABLE auth_role_manageable_roles (
  id BIGSERIAL PRIMARY KEY,
  role_id BIGINT NOT NULL REFERENCES auth_roles(id) ON DELETE CASCADE,
  manageable_role_id BIGINT NOT NULL REFERENCES auth_roles(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (role_id, manageable_role_id),
  CHECK (role_id <> manageable_role_id)
);

CREATE TABLE auth_metrics (
  id BIGSERIAL PRIMARY KEY,
  tenant_id BIGINT NOT NULL REFERENCES auth_tenants(id),
  metric_key VARCHAR(160) NOT NULL,
  metric_name VARCHAR(160) NOT NULL,
  metric_definition TEXT,
  source_table VARCHAR(160),
  allowed_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
  row_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by BIGINT NOT NULL REFERENCES auth_users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, metric_key)
);

CREATE TABLE auth_audit_logs (
  id BIGSERIAL PRIMARY KEY,
  tenant_id BIGINT REFERENCES auth_tenants(id),
  actor_user_id BIGINT REFERENCES auth_users(id),
  action VARCHAR(64) NOT NULL,
  target_type VARCHAR(64) NOT NULL,
  target_id VARCHAR(160),
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_auth_user_roles_user_tenant ON auth_user_roles(user_id, tenant_id);
CREATE INDEX idx_auth_roles_tenant_level ON auth_roles(tenant_id, role_level);
CREATE INDEX idx_auth_permissions_resource_action ON auth_permissions(resource_key, action);
CREATE INDEX idx_auth_metrics_tenant ON auth_metrics(tenant_id);

CREATE UNIQUE INDEX uq_auth_roles_single_global_super_admin
  ON auth_roles (role_level)
  WHERE role_level = 100 AND tenant_id IS NULL;

CREATE UNIQUE INDEX uq_auth_user_roles_tenant_role
  ON auth_user_roles (user_id, tenant_id, role_id)
  WHERE tenant_id IS NOT NULL;

CREATE UNIQUE INDEX uq_auth_user_roles_global_role
  ON auth_user_roles (user_id, role_id)
  WHERE tenant_id IS NULL;
