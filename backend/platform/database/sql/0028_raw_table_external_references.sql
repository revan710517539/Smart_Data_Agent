CREATE TABLE IF NOT EXISTS platform_raw_table_external_references (
    tenant_id TEXT NOT NULL,
    source_key TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('private', 'shared')),
    schema_fingerprint TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, source_key)
);

CREATE INDEX IF NOT EXISTS idx_platform_raw_table_external_references_tenant_mode
    ON platform_raw_table_external_references(tenant_id, mode, updated_at DESC);
