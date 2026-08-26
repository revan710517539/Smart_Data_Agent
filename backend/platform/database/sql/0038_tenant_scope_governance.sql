CREATE TABLE IF NOT EXISTS platform_tenant_topic_assignments (
    assignment_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    topic_skill_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked')),
    assigned_by TEXT NOT NULL DEFAULT '',
    assigned_at TEXT NOT NULL,
    expires_at TEXT NOT NULL DEFAULT '',
    revoked_by TEXT NOT NULL DEFAULT '',
    revoked_at TEXT NOT NULL DEFAULT '',
    revoke_reason TEXT NOT NULL DEFAULT '',
    UNIQUE (tenant_id, topic_skill_id)
);

CREATE INDEX IF NOT EXISTS idx_tenant_topic_assignment_status
    ON platform_tenant_topic_assignments(tenant_id, status, expires_at);

CREATE TABLE IF NOT EXISTS platform_cross_tenant_resource_grants (
    grant_id TEXT PRIMARY KEY,
    source_tenant_id TEXT NOT NULL,
    recipient_tenant_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_key TEXT NOT NULL,
    actions TEXT NOT NULL DEFAULT '[]',
    field_scope TEXT NOT NULL DEFAULT '[]',
    schema_fingerprint TEXT NOT NULL,
    purpose TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked')),
    effective_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',
    approved_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    revoked_by TEXT NOT NULL DEFAULT '',
    revoked_at TEXT NOT NULL DEFAULT '',
    revoke_reason TEXT NOT NULL DEFAULT '',
    CHECK (source_tenant_id <> recipient_tenant_id),
    CHECK (expires_at > effective_at)
);

CREATE INDEX IF NOT EXISTS idx_cross_tenant_grant_recipient
    ON platform_cross_tenant_resource_grants(recipient_tenant_id, status, expires_at);

CREATE INDEX IF NOT EXISTS idx_cross_tenant_grant_resource
    ON platform_cross_tenant_resource_grants(source_tenant_id, resource_type, resource_key, status);
