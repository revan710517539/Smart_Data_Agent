CREATE TABLE platform_user_interaction_events (
  interaction_event_id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
  tenant_id CHAR(36) NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE,
  actor_user_id CHAR(36) REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL,
  actor_account VARCHAR(320) NOT NULL DEFAULT '',
  event_name VARCHAR(120) NOT NULL,
  event_type VARCHAR(16) NOT NULL CHECK (event_type IN ('click','view')),
  page_path VARCHAR(500) NOT NULL DEFAULT '',
  page_name VARCHAR(200) NOT NULL DEFAULT '',
  chart_id VARCHAR(200),
  chart_name VARCHAR(300),
  resource_type VARCHAR(120),
  resource_id VARCHAR(200),
  extension JSON NOT NULL DEFAULT (JSON_OBJECT()),
  occurred_at DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
  created_by CHAR(36) REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL,
  created_at DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
  updated_at DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
  lock_version BIGINT NOT NULL DEFAULT 0 CHECK (lock_version >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='产品页面和可视化控件的脱敏用户交互事件。';

CREATE INDEX idx_platform_interaction_tenant_time
  ON platform_user_interaction_events (tenant_id, occurred_at, interaction_event_id);
CREATE INDEX idx_platform_interaction_actor_time
  ON platform_user_interaction_events (tenant_id, actor_user_id, occurred_at);
CREATE INDEX idx_platform_interaction_event_name
  ON platform_user_interaction_events (tenant_id, event_name, occurred_at);
