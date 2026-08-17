CREATE TABLE platform_bridge_enrollments (
    enrollment_id TEXT PRIMARY KEY,
    device_code_hash TEXT NOT NULL UNIQUE,
    user_code_hash TEXT NOT NULL UNIQUE,
    channel TEXT NOT NULL CHECK (channel IN ('workbuddy', 'codex', 'qwork')),
    device_name TEXT NOT NULL,
    verifier_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'consumed')),
    tenant_id TEXT,
    user_id TEXT,
    approved_by TEXT,
    expires_at INTEGER NOT NULL,
    approved_at INTEGER,
    consumed_at INTEGER,
    binding_id TEXT,
    created_at INTEGER NOT NULL
);

CREATE INDEX idx_platform_bridge_enrollments_expiry
    ON platform_bridge_enrollments(status, expires_at);

CREATE TABLE platform_bridge_bindings (
    binding_id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    channel TEXT NOT NULL CHECK (channel IN ('workbuddy', 'codex', 'qwork')),
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'tenant')),
    label TEXT NOT NULL,
    device_name TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    revoked_at INTEGER
);

CREATE INDEX idx_platform_bridge_bindings_owner
    ON platform_bridge_bindings(tenant_id, user_id, channel, revoked_at);
