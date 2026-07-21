-- Persist every model invocation as a tenant-scoped, immutable audit fact.
-- Raw prompts, provider responses and credentials are deliberately excluded;
-- hashes bind the call to the exact request/response without retaining data.

CREATE TABLE IF NOT EXISTS platform_model_calls (
    model_call_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    analysis_task_id TEXT NOT NULL REFERENCES platform_analysis_tasks(task_id) ON DELETE CASCADE,
    execution_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    model_integration_id TEXT NOT NULL,
    provider_model_name TEXT NOT NULL DEFAULT '',
    prompt_template_id TEXT,
    request_hash TEXT NOT NULL CHECK (length(request_hash) = 64),
    response_hash TEXT NOT NULL DEFAULT '' CHECK (response_hash = '' OR length(response_hash) = 64),
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'degraded', 'failed', 'cancelled')),
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    usage_source TEXT NOT NULL DEFAULT 'estimated' CHECK (usage_source IN ('provider', 'estimated')),
    cost_amount REAL NOT NULL DEFAULT 0 CHECK (cost_amount >= 0),
    latency_ms INTEGER NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
    error_code TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(analysis_task_id, revision)
);

CREATE INDEX IF NOT EXISTS idx_platform_model_calls_task
    ON platform_model_calls(tenant_id, analysis_task_id, created_at);
CREATE INDEX IF NOT EXISTS idx_platform_model_calls_model
    ON platform_model_calls(tenant_id, model_integration_id, created_at);
