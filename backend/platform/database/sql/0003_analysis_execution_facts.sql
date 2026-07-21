-- Bind plans, executed queries, artifacts, evidence and evaluations to one
-- immutable analysis execution identity. SQLite keeps a compatibility subset
-- of the production PostgreSQL catalog.

ALTER TABLE platform_analysis_tasks ADD COLUMN request_id TEXT NOT NULL DEFAULT '';
ALTER TABLE platform_analysis_tasks ADD COLUMN execution_id TEXT NOT NULL DEFAULT '';
ALTER TABLE platform_analysis_tasks ADD COLUMN revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0);
ALTER TABLE platform_analysis_tasks ADD COLUMN parent_execution_id TEXT;
ALTER TABLE platform_analysis_tasks ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'mock' CHECK (execution_mode IN ('real', 'mock', 'degraded'));
ALTER TABLE platform_analysis_tasks ADD COLUMN manual_edits TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(manual_edits));
ALTER TABLE platform_analysis_tasks ADD COLUMN agent_group_state TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(agent_group_state));

CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_analysis_tasks_request
    ON platform_analysis_tasks(tenant_id, request_id)
    WHERE request_id <> '';
CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_analysis_tasks_execution
    ON platform_analysis_tasks(execution_id)
    WHERE execution_id <> '';
CREATE INDEX IF NOT EXISTS idx_platform_analysis_tasks_parent
    ON platform_analysis_tasks(parent_execution_id, revision);

CREATE TABLE IF NOT EXISTS platform_analysis_queries (
    analysis_query_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    analysis_task_id TEXT NOT NULL REFERENCES platform_analysis_tasks(task_id) ON DELETE CASCADE,
    execution_id TEXT NOT NULL,
    query_revision INTEGER NOT NULL CHECK (query_revision > 0),
    dataset_id TEXT NOT NULL,
    connection_id TEXT NOT NULL DEFAULT '',
    compiled_sql TEXT NOT NULL DEFAULT '',
    sql_executed INTEGER NOT NULL DEFAULT 0 CHECK (sql_executed IN (0, 1)),
    sql_hash TEXT NOT NULL DEFAULT '',
    parameters TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(parameters)),
    policy_snapshot TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(policy_snapshot)),
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed', 'cancelled', 'not_executed_mock')),
    result_hash TEXT NOT NULL DEFAULT '',
    row_count INTEGER NOT NULL DEFAULT 0 CHECK (row_count >= 0),
    summary TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(summary)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(analysis_task_id, query_revision)
);

CREATE INDEX IF NOT EXISTS idx_platform_analysis_queries_execution
    ON platform_analysis_queries(tenant_id, execution_id, query_revision);
CREATE INDEX IF NOT EXISTS idx_platform_analysis_queries_hash
    ON platform_analysis_queries(tenant_id, sql_hash);

CREATE TABLE IF NOT EXISTS platform_analysis_artifacts (
    analysis_artifact_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    analysis_task_id TEXT NOT NULL REFERENCES platform_analysis_tasks(task_id) ON DELETE CASCADE,
    execution_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    artifact_type TEXT NOT NULL CHECK (artifact_type IN ('plan', 'python_script', 'chart', 'table', 'conclusion', 'model_draft', 'review', 'export')),
    execution_status TEXT NOT NULL CHECK (execution_status IN ('draft', 'executed', 'verified', 'rejected')),
    content TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(content)),
    content_hash TEXT NOT NULL,
    parent_artifact_id TEXT REFERENCES platform_analysis_artifacts(analysis_artifact_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(analysis_task_id, revision, artifact_type)
);

CREATE TABLE IF NOT EXISTS platform_analysis_evidence (
    analysis_evidence_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    analysis_task_id TEXT NOT NULL REFERENCES platform_analysis_tasks(task_id) ON DELETE CASCADE,
    execution_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL CHECK (evidence_type IN ('query', 'partition', 'row', 'aggregate', 'knowledge', 'market', 'quality')),
    evidence_ref_id TEXT NOT NULL,
    metric_id TEXT NOT NULL DEFAULT '',
    dimension_context TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(dimension_context)),
    observed_value TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(observed_value)),
    evidence_hash TEXT NOT NULL,
    freshness_status TEXT NOT NULL DEFAULT 'unknown' CHECK (freshness_status IN ('fresh', 'stale', 'unknown', 'blocked')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_platform_analysis_evidence_execution
    ON platform_analysis_evidence(tenant_id, execution_id, evidence_type);

CREATE TABLE IF NOT EXISTS platform_evaluations (
    evaluation_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    analysis_task_id TEXT NOT NULL REFERENCES platform_analysis_tasks(task_id) ON DELETE CASCADE,
    execution_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    evaluation_type TEXT NOT NULL CHECK (evaluation_type IN ('sql_data_match', 'metric_correctness', 'faithfulness', 'permission', 'freshness', 'visualization', 'overall')),
    status TEXT NOT NULL CHECK (status IN ('passed', 'warning', 'failed', 'error')),
    score REAL NOT NULL CHECK (score BETWEEN 0 AND 1),
    checks TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(checks)),
    evaluated_artifact_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(analysis_task_id, revision, evaluation_type)
);
