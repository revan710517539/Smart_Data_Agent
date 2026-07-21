-- Automation task definitions are server-owned and updated with optimistic locking.

ALTER TABLE platform_automation_tasks
    ADD COLUMN lock_version INTEGER NOT NULL DEFAULT 0 CHECK (lock_version >= 0);

CREATE INDEX IF NOT EXISTS idx_automation_tasks_owner
    ON platform_automation_tasks(tenant_id, owner_user_id, updated_at DESC);
