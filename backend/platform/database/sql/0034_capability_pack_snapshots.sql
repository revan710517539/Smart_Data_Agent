ALTER TABLE platform_account_capabilities
    ADD COLUMN permission_scope_json TEXT NOT NULL DEFAULT '[]';

CREATE TABLE IF NOT EXISTS platform_capability_pack_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    entries_json TEXT NOT NULL DEFAULT '[]',
    entry_count INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_capability_pack_account
    ON platform_capability_pack_snapshots(tenant_id, user_id, created_at);
