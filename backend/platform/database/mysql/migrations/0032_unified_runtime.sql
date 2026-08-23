CREATE TABLE platform_account_capabilities (
  capability_row_id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
  tenant_id VARCHAR(160) NOT NULL,
  owner_scope VARCHAR(16) NOT NULL,
  owner_id VARCHAR(160) NOT NULL,
  capability_id VARCHAR(160) NOT NULL,
  version VARCHAR(32) NOT NULL DEFAULT '1.0.0',
  kind VARCHAR(24) NOT NULL,
  runtime_type VARCHAR(32) NOT NULL,
  status VARCHAR(24) NOT NULL DEFAULT 'candidate',
  title VARCHAR(300) NOT NULL DEFAULT '',
  description VARCHAR(1000) NOT NULL DEFAULT '',
  trigger_json JSON NOT NULL,
  body_json JSON NOT NULL,
  fingerprint CHAR(64) NOT NULL,
  created_by VARCHAR(160) NOT NULL DEFAULT '',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_account_capability (tenant_id, owner_scope, owner_id, capability_id, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Account-scoped runtime capabilities. User rows are isolated by owner_id.';

CREATE INDEX idx_account_capability_visible
  ON platform_account_capabilities (tenant_id, owner_scope, owner_id, status);
CREATE INDEX idx_account_capability_fingerprint
  ON platform_account_capabilities (tenant_id, fingerprint, status);

CREATE TABLE platform_runtime_episodes (
  episode_id VARCHAR(64) PRIMARY KEY,
  tenant_id VARCHAR(160) NOT NULL,
  user_id VARCHAR(160) NOT NULL,
  session_id VARCHAR(160) NOT NULL DEFAULT '',
  parent_episode_id VARCHAR(64),
  pack_snapshot_id VARCHAR(80) NOT NULL DEFAULT '',
  status VARCHAR(24) NOT NULL DEFAULT 'running',
  task_id VARCHAR(80) NOT NULL DEFAULT '',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Runtime analysis/learning episodes keyed by account.';

CREATE INDEX idx_runtime_episodes_account
  ON platform_runtime_episodes (tenant_id, user_id, created_at);

CREATE TABLE platform_capability_evals (
  eval_id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
  tenant_id VARCHAR(160) NOT NULL,
  user_id VARCHAR(160) NOT NULL DEFAULT '',
  capability_id VARCHAR(160) NOT NULL DEFAULT '',
  episode_id VARCHAR(64) NOT NULL DEFAULT '',
  metric VARCHAR(80) NOT NULL DEFAULT 'episode',
  score DECIMAL(7,4),
  status VARCHAR(24) NOT NULL DEFAULT '',
  detail_json JSON NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Runtime eval scores for pack promotion and delivery quality.';

CREATE INDEX idx_capability_evals_account
  ON platform_capability_evals (tenant_id, capability_id, created_at);
