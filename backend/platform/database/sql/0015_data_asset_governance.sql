ALTER TABLE platform_data_asset_items
    ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'review'
    CHECK (lifecycle_status IN ('draft', 'review', 'active', 'rejected', 'archived'));

ALTER TABLE platform_data_asset_items
    ADD COLUMN current_version INTEGER NOT NULL DEFAULT 1 CHECK (current_version >= 1);

ALTER TABLE platform_data_asset_items
    ADD COLUMN schema_version TEXT NOT NULL DEFAULT '1.0';

ALTER TABLE platform_data_asset_items
    ADD COLUMN lock_version INTEGER NOT NULL DEFAULT 1 CHECK (lock_version >= 1);

ALTER TABLE platform_data_asset_items ADD COLUMN submitted_by TEXT;
ALTER TABLE platform_data_asset_items ADD COLUMN reviewed_by TEXT;
ALTER TABLE platform_data_asset_items ADD COLUMN reviewed_at TEXT;
ALTER TABLE platform_data_asset_items ADD COLUMN published_at TEXT;

UPDATE platform_data_asset_items
SET lifecycle_status = CASE
        WHEN updated_by = 'development_seed' THEN 'active'
        ELSE 'review'
    END,
    submitted_by = COALESCE(updated_by, created_by),
    published_at = CASE
        WHEN updated_by = 'development_seed' THEN COALESCE(updated_at, CURRENT_TIMESTAMP)
        ELSE NULL
    END;

CREATE TABLE platform_data_asset_versions (
    tenant_id TEXT NOT NULL,
    item_type TEXT NOT NULL,
    item_id TEXT NOT NULL,
    version_number INTEGER NOT NULL CHECK (version_number >= 1),
    schema_version TEXT NOT NULL DEFAULT '1.0',
    lifecycle_status TEXT NOT NULL
        CHECK (lifecycle_status IN ('draft', 'review', 'active', 'rejected', 'archived')),
    title TEXT NOT NULL,
    payload TEXT NOT NULL CHECK (json_valid(payload)),
    payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
    submitted_by TEXT NOT NULL,
    submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_by TEXT,
    reviewed_at TEXT,
    review_comment TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (tenant_id, item_type, item_id, version_number),
    FOREIGN KEY (tenant_id, item_type, item_id)
        REFERENCES platform_data_asset_items(tenant_id, item_type, item_id)
        ON DELETE CASCADE
);

CREATE TABLE platform_data_asset_reviews (
    review_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    item_type TEXT NOT NULL,
    item_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected', 'changes_required')),
    reviewer_user_id TEXT NOT NULL,
    comments TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id, item_type, item_id, version_number)
        REFERENCES platform_data_asset_versions(tenant_id, item_type, item_id, version_number)
        ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_platform_data_asset_active_version
    ON platform_data_asset_versions(tenant_id, item_type, item_id)
    WHERE lifecycle_status = 'active';

CREATE INDEX idx_platform_data_asset_versions_review_queue
    ON platform_data_asset_versions(tenant_id, lifecycle_status, submitted_at DESC);

CREATE INDEX idx_platform_data_asset_reviews_item
    ON platform_data_asset_reviews(tenant_id, item_type, item_id, version_number, created_at DESC);

INSERT INTO platform_data_asset_versions(
    tenant_id, item_type, item_id, version_number, schema_version,
    lifecycle_status, title, payload, payload_hash, submitted_by,
    submitted_at, reviewed_by, reviewed_at
)
SELECT
    tenant_id,
    item_type,
    item_id,
    1,
    '1.0',
    lifecycle_status,
    title,
    payload,
    lower(hex(zeroblob(32))),
    COALESCE(updated_by, created_by, 'migration'),
    COALESCE(updated_at, CURRENT_TIMESTAMP),
    reviewed_by,
    reviewed_at
FROM platform_data_asset_items;
