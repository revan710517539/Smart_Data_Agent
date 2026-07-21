-- Owner-scoped subscription concurrency and idempotent provider receipts.

ALTER TABLE platform_subscriptions ADD COLUMN lock_version INTEGER NOT NULL DEFAULT 1 CHECK (lock_version > 0);
ALTER TABLE platform_subscriptions ADD COLUMN disabled_at TEXT;

CREATE TABLE IF NOT EXISTS platform_provider_callbacks (
    tenant_id TEXT NOT NULL,
    callback_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    provider_message_id TEXT,
    event_type TEXT NOT NULL,
    signature_valid INTEGER NOT NULL CHECK (signature_valid IN (0, 1)),
    payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
    safe_payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(safe_payload)),
    processing_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (processing_status IN ('pending','processed','ignored','failed')),
    processed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, callback_id),
    UNIQUE (provider, provider_event_id)
);

CREATE INDEX IF NOT EXISTS idx_platform_provider_callbacks_pending
    ON platform_provider_callbacks(processing_status, created_at);
CREATE INDEX IF NOT EXISTS idx_platform_provider_callbacks_message
    ON platform_provider_callbacks(tenant_id, provider_message_id, created_at);
