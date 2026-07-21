CREATE TABLE platform_capability_approvals (
    approval_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('skill', 'mcp')),
    subject_id TEXT NOT NULL,
    action TEXT NOT NULL,
    input_hash TEXT NOT NULL CHECK (length(input_hash) = 64),
    reason TEXT NOT NULL DEFAULT '',
    requested_by TEXT NOT NULL,
    requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'expired', 'consumed')),
    reviewed_by TEXT,
    reviewed_at TEXT,
    expires_at TEXT,
    consumed_at TEXT,
    review_comment TEXT NOT NULL DEFAULT ''
);

CREATE INDEX idx_platform_capability_approvals_queue
    ON platform_capability_approvals(tenant_id, status, requested_at DESC);

CREATE INDEX idx_platform_capability_approvals_subject
    ON platform_capability_approvals(tenant_id, subject_type, subject_id, requested_by, status);
