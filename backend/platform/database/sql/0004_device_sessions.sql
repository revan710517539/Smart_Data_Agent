CREATE TABLE IF NOT EXISTS platform_auth_sessions (
    device_session_id TEXT PRIMARY KEY,
    access_jti TEXT NOT NULL UNIQUE,
    refresh_token_hash TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    primary_tenant_id TEXT NOT NULL,
    tenant_ids TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tenant_ids)),
    issued_at INTEGER NOT NULL,
    access_expires_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    idle_expires_at INTEGER NOT NULL,
    absolute_expires_at INTEGER NOT NULL,
    idle_timeout_seconds INTEGER NOT NULL CHECK (idle_timeout_seconds >= 60),
    revoked_at INTEGER,
    revoke_reason TEXT NOT NULL DEFAULT '',
    rotated_at INTEGER,
    user_agent_hash TEXT NOT NULL DEFAULT '',
    ip_prefix TEXT NOT NULL DEFAULT '',
    CHECK (access_expires_at <= absolute_expires_at),
    CHECK (idle_expires_at <= absolute_expires_at)
);

CREATE INDEX IF NOT EXISTS idx_platform_auth_sessions_user_active
    ON platform_auth_sessions(user_id, revoked_at, absolute_expires_at);
CREATE INDEX IF NOT EXISTS idx_platform_auth_sessions_refresh
    ON platform_auth_sessions(refresh_token_hash);
