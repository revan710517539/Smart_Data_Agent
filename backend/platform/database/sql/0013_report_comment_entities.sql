-- Server-authored report comment entities. The legacy snapshot table remains
-- readable during migration, while all new writes use row-level records.

CREATE TABLE IF NOT EXISTS platform_report_comment_items (
    tenant_id TEXT NOT NULL,
    report_id TEXT NOT NULL,
    comment_id TEXT NOT NULL,
    client_request_id TEXT,
    target_id TEXT NOT NULL,
    target_label TEXT NOT NULL,
    target_kind TEXT,
    selected_text TEXT,
    block_id TEXT,
    item_id TEXT,
    range_start INTEGER,
    range_end INTEGER,
    anchor_top REAL,
    author_user_id TEXT NOT NULL,
    comment_body TEXT NOT NULL CHECK (length(trim(comment_body)) > 0),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','reopened','deleted')),
    resolved_by TEXT,
    resolved_at TEXT,
    resolved_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    lock_version INTEGER NOT NULL DEFAULT 0 CHECK (lock_version >= 0),
    PRIMARY KEY (tenant_id, report_id, comment_id),
    UNIQUE (tenant_id, report_id, client_request_id)
);

CREATE INDEX IF NOT EXISTS idx_report_comment_items_status
    ON platform_report_comment_items(tenant_id, report_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS platform_report_comment_replies (
    tenant_id TEXT NOT NULL,
    report_id TEXT NOT NULL,
    comment_id TEXT NOT NULL,
    reply_id TEXT NOT NULL,
    client_request_id TEXT,
    author_user_id TEXT NOT NULL,
    reply_body TEXT NOT NULL CHECK (length(trim(reply_body)) > 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','deleted')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    lock_version INTEGER NOT NULL DEFAULT 0 CHECK (lock_version >= 0),
    PRIMARY KEY (tenant_id, report_id, reply_id),
    UNIQUE (tenant_id, report_id, client_request_id),
    FOREIGN KEY (tenant_id, report_id, comment_id)
        REFERENCES platform_report_comment_items(tenant_id, report_id, comment_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_report_comment_replies_comment
    ON platform_report_comment_replies(tenant_id, report_id, comment_id, created_at);
