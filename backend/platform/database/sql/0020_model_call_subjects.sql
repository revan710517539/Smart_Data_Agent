-- Model calls also originate from acquisition repair, report generation and
-- other governed subjects.  Keep analysis_task_id optional and bind every call
-- to an explicit subject identity.

ALTER TABLE platform_model_calls RENAME TO platform_model_calls_legacy;

CREATE TABLE platform_model_calls (
    model_call_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    analysis_task_id TEXT REFERENCES platform_analysis_tasks(task_id) ON DELETE CASCADE,
    execution_id TEXT NOT NULL DEFAULT '',
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
    UNIQUE(tenant_id, subject_type, subject_id, revision)
);

INSERT INTO platform_model_calls(
    model_call_id, tenant_id, subject_type, subject_id, analysis_task_id,
    execution_id, revision, model_integration_id, provider_model_name,
    prompt_template_id, request_hash, response_hash, status, input_tokens,
    output_tokens, usage_source, cost_amount, latency_ms, error_code,
    created_by, created_at
)
SELECT
    model_call_id, tenant_id, 'analysis_task', analysis_task_id, analysis_task_id,
    execution_id, revision, model_integration_id, provider_model_name,
    prompt_template_id, request_hash, response_hash, status, input_tokens,
    output_tokens, usage_source, cost_amount, latency_ms, error_code,
    created_by, created_at
FROM platform_model_calls_legacy;

DROP TABLE platform_model_calls_legacy;

CREATE INDEX idx_platform_model_calls_task
    ON platform_model_calls(tenant_id, analysis_task_id, created_at);
CREATE INDEX idx_platform_model_calls_subject
    ON platform_model_calls(tenant_id, subject_type, subject_id, created_at);
CREATE INDEX idx_platform_model_calls_model
    ON platform_model_calls(tenant_id, model_integration_id, created_at);
