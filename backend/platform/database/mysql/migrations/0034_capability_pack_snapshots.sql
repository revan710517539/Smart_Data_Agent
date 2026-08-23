ALTER TABLE platform_account_capabilities
  ADD COLUMN permission_scope_json JSON NULL AFTER body_json;

UPDATE platform_account_capabilities
SET permission_scope_json = JSON_ARRAY()
WHERE permission_scope_json IS NULL;

ALTER TABLE platform_account_capabilities
  MODIFY COLUMN permission_scope_json JSON NOT NULL;

CREATE TABLE platform_capability_pack_snapshots (
  snapshot_id VARCHAR(80) PRIMARY KEY,
  tenant_id VARCHAR(160) NOT NULL,
  user_id VARCHAR(160) NOT NULL,
  entries_json JSON NOT NULL,
  entry_count INTEGER NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Immutable request-scoped capability pack snapshots.';

CREATE INDEX idx_capability_pack_account
  ON platform_capability_pack_snapshots (tenant_id, user_id, created_at);
