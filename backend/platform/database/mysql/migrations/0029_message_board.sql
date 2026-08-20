CREATE TABLE IF NOT EXISTS platform_message_board_entries (
  message_id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
  message_key VARCHAR(80) NOT NULL UNIQUE,
  tenant_id CHAR(36) NOT NULL REFERENCES platform_tenants(tenant_id) ON DELETE CASCADE,
  author_user_id CHAR(36) NOT NULL REFERENCES platform_user_profiles(user_id) ON DELETE RESTRICT,
  author_name VARCHAR(200) NOT NULL,
  page_key VARCHAR(160) NOT NULL,
  page_title VARCHAR(240) NOT NULL,
  page_url VARCHAR(1000) NOT NULL DEFAULT '',
  content TEXT NOT NULL,
  quote_context JSON NOT NULL DEFAULT (JSON_OBJECT()),
  attachment_ids JSON NOT NULL DEFAULT (JSON_ARRAY()),
  created_by CHAR(36) REFERENCES platform_user_profiles(user_id) ON DELETE SET NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  lock_version BIGINT NOT NULL DEFAULT 0 CHECK (lock_version >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户从各业务页面提交的产品意见与需求留言。';

CREATE INDEX idx_platform_message_board_owner_page
  ON platform_message_board_entries (tenant_id, author_user_id, page_key, created_at);

CREATE INDEX idx_platform_message_board_created
  ON platform_message_board_entries (created_at, message_id);
