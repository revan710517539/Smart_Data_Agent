CREATE TABLE IF NOT EXISTS platform_daily_report_runs (
    tenant_id TEXT NOT NULL,
    daily_report_run_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    report_date TEXT NOT NULL,
    source_report_version_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    body_artifact_id TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    evidence_summary TEXT NOT NULL DEFAULT '{}',
    preview_text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('generated','queued','sending','delivered','failed')),
    outbox_event_id TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, daily_report_run_id),
    UNIQUE (tenant_id, owner_user_id, report_date, content_hash),
    FOREIGN KEY (tenant_id, source_report_version_id)
        REFERENCES platform_weekly_report_versions(tenant_id, version_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, body_artifact_id)
        REFERENCES platform_data_artifacts(tenant_id, artifact_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, outbox_event_id)
        REFERENCES platform_outbox_events(tenant_id, outbox_event_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_platform_daily_report_runs_owner
    ON platform_daily_report_runs(tenant_id, owner_user_id, report_date DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS platform_email_messages (
    tenant_id TEXT NOT NULL,
    email_message_id TEXT NOT NULL,
    delivery_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    body_artifact_id TEXT NOT NULL,
    from_address TEXT NOT NULL,
    to_addresses TEXT NOT NULL DEFAULT '[]',
    cc_addresses TEXT NOT NULL DEFAULT '[]',
    attachment_ids TEXT NOT NULL DEFAULT '[]',
    provider_response TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, email_message_id),
    UNIQUE (tenant_id, delivery_id),
    FOREIGN KEY (tenant_id, delivery_id)
        REFERENCES platform_notification_deliveries(tenant_id, delivery_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, body_artifact_id)
        REFERENCES platform_data_artifacts(tenant_id, artifact_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_platform_email_messages_created
    ON platform_email_messages(tenant_id, created_at DESC);
