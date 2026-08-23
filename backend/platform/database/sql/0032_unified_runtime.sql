CREATE TABLE IF NOT EXISTS platform_account_capabilities (
    tenant_id TEXT NOT NULL,
    owner_scope TEXT NOT NULL CHECK (owner_scope IN ('user','role','org','tenant','platform')),
    owner_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '1.0.0',
    kind TEXT NOT NULL,
    runtime_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate',
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    trigger_json TEXT NOT NULL DEFAULT '{}',
    body_json TEXT NOT NULL DEFAULT '{}',
    fingerprint TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, owner_scope, owner_id, capability_id, version)
);

CREATE INDEX IF NOT EXISTS idx_account_capability_visible
    ON platform_account_capabilities(tenant_id, owner_scope, owner_id, status);

CREATE TABLE IF NOT EXISTS platform_runtime_episodes (
    episode_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    parent_episode_id TEXT,
    pack_snapshot_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'running',
    task_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runtime_episodes_account
    ON platform_runtime_episodes(tenant_id, user_id, created_at);
