-- Durable automation, worker and notification projections for the local adapter.

CREATE TABLE IF NOT EXISTS platform_automation_tasks (
    tenant_id TEXT NOT NULL,
    automation_task_id TEXT NOT NULL,
    task_code TEXT NOT NULL,
    task_name TEXT NOT NULL,
    task_type TEXT NOT NULL CHECK (task_type IN ('acquisition','analysis','report','export','notification','quality','market_monitoring','custom')),
    trigger_type TEXT NOT NULL CHECK (trigger_type IN ('manual','schedule','event')),
    schedule_expression TEXT,
    event_type TEXT,
    handler_ref TEXT NOT NULL,
    task_config TEXT NOT NULL DEFAULT '{}',
    retry_policy TEXT NOT NULL DEFAULT '{}',
    timeout_seconds INTEGER NOT NULL DEFAULT 900 CHECK (timeout_seconds BETWEEN 1 AND 86400),
    max_concurrency INTEGER NOT NULL DEFAULT 1 CHECK (max_concurrency BETWEEN 1 AND 100),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','disabled')),
    next_run_at TEXT,
    owner_user_id TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, automation_task_id),
    UNIQUE (tenant_id, task_code)
);

CREATE TABLE IF NOT EXISTS platform_automation_task_runs (
    tenant_id TEXT NOT NULL,
    automation_run_id TEXT NOT NULL,
    automation_task_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    trigger_payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK (status IN ('queued','running','retry_wait','succeeded','failed','cancelled')),
    attempt_no INTEGER NOT NULL DEFAULT 1 CHECK (attempt_no > 0),
    lease_owner TEXT,
    lease_expires_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    next_retry_at TEXT,
    result_refs TEXT NOT NULL DEFAULT '[]',
    error_code TEXT,
    error_summary TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, automation_run_id),
    UNIQUE (tenant_id, automation_task_id, idempotency_key),
    FOREIGN KEY (tenant_id, automation_task_id)
        REFERENCES platform_automation_tasks(tenant_id, automation_task_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS platform_job_steps (
    tenant_id TEXT NOT NULL,
    job_step_id TEXT NOT NULL,
    automation_run_id TEXT NOT NULL,
    step_code TEXT NOT NULL,
    sequence_no INTEGER NOT NULL CHECK (sequence_no >= 0),
    status TEXT NOT NULL CHECK (status IN ('pending','running','succeeded','failed','skipped','compensated')),
    checkpoint TEXT NOT NULL DEFAULT '{}',
    input_refs TEXT NOT NULL DEFAULT '[]',
    output_refs TEXT NOT NULL DEFAULT '[]',
    started_at TEXT,
    finished_at TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, job_step_id),
    UNIQUE (tenant_id, automation_run_id, step_code),
    FOREIGN KEY (tenant_id, automation_run_id)
        REFERENCES platform_automation_task_runs(tenant_id, automation_run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS platform_subscriptions (
    tenant_id TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    subscription_name TEXT NOT NULL,
    event_types TEXT NOT NULL,
    channel_type TEXT NOT NULL CHECK (channel_type IN ('in_app','email','webhook')),
    channel_config_secret TEXT NOT NULL DEFAULT '{}',
    filter_expression TEXT NOT NULL DEFAULT '{}',
    quiet_hours TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','disabled')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, subscription_id)
);

CREATE TABLE IF NOT EXISTS platform_notification_deliveries (
    tenant_id TEXT NOT NULL,
    delivery_id TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    outbox_event_id TEXT NOT NULL,
    channel_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued','sending','delivered','failed','suppressed','dead_letter')),
    idempotency_key TEXT NOT NULL,
    attempt_no INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    provider_message_id TEXT,
    error_code TEXT,
    delivered_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, delivery_id),
    UNIQUE (tenant_id, subscription_id, outbox_event_id),
    FOREIGN KEY (tenant_id, subscription_id)
        REFERENCES platform_subscriptions(tenant_id, subscription_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, outbox_event_id)
        REFERENCES platform_outbox_events(tenant_id, outbox_event_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_automation_tasks_due
    ON platform_automation_tasks(status, next_run_at);
CREATE INDEX IF NOT EXISTS idx_automation_runs_claim
    ON platform_automation_task_runs(status, next_retry_at, created_at);
CREATE INDEX IF NOT EXISTS idx_notification_delivery_claim
    ON platform_notification_deliveries(status, next_attempt_at, created_at);
