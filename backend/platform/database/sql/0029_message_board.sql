CREATE TABLE IF NOT EXISTS platform_message_board_entries (
    message_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    author_user_id TEXT NOT NULL,
    author_name TEXT NOT NULL,
    page_key TEXT NOT NULL,
    page_title TEXT NOT NULL,
    page_url TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    quote_context TEXT NOT NULL DEFAULT '{}',
    attachment_ids TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'adopted', 'completed')),
    archived_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    lock_version INTEGER NOT NULL DEFAULT 0 CHECK (lock_version >= 0)
);

CREATE INDEX IF NOT EXISTS idx_platform_message_board_owner_page
    ON platform_message_board_entries(tenant_id, author_user_id, page_key, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_platform_message_board_created
    ON platform_message_board_entries(created_at DESC, message_id);
