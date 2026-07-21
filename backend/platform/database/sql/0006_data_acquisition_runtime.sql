-- Local/runtime projection of the governed data-acquisition facts.  Production
-- PostgreSQL uses the generated 93-table schema catalog.

CREATE TABLE IF NOT EXISTS platform_source_systems (
    tenant_id TEXT NOT NULL,
    source_system_id TEXT NOT NULL,
    source_code TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_category TEXT NOT NULL CHECK (source_category IN (
        'internal_operation','yushu','smart_operation','market','warehouse','file_exchange','other'
    )),
    license_metadata TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','degraded','disabled','retired')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, source_system_id),
    UNIQUE (tenant_id, source_code)
);

CREATE TABLE IF NOT EXISTS platform_acquisition_scripts (
    tenant_id TEXT NOT NULL,
    acquisition_script_id TEXT NOT NULL,
    script_code TEXT NOT NULL,
    script_name TEXT NOT NULL,
    runtime TEXT NOT NULL CHECK (runtime IN ('python','sql','http','shell_restricted')),
    current_version_no INTEGER NOT NULL DEFAULT 0 CHECK (current_version_no >= 0),
    owner_user_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'review' CHECK (status IN ('draft','review','active','degraded','disabled')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, acquisition_script_id),
    UNIQUE (tenant_id, script_code)
);

CREATE TABLE IF NOT EXISTS platform_acquisition_script_versions (
    tenant_id TEXT NOT NULL,
    script_version_id TEXT NOT NULL,
    acquisition_script_id TEXT NOT NULL,
    version_no INTEGER NOT NULL CHECK (version_no > 0),
    source_code TEXT NOT NULL,
    source_hash TEXT NOT NULL CHECK (length(source_hash) = 64),
    dependency_lock TEXT NOT NULL DEFAULT '{}',
    input_schema TEXT NOT NULL DEFAULT '{}',
    output_schema TEXT NOT NULL DEFAULT '{}',
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending','approved','rejected','revoked')),
    reviewed_by TEXT,
    reviewed_at TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, script_version_id),
    UNIQUE (tenant_id, acquisition_script_id, version_no),
    FOREIGN KEY (tenant_id, acquisition_script_id)
        REFERENCES platform_acquisition_scripts(tenant_id, acquisition_script_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS platform_acquisition_jobs (
    tenant_id TEXT NOT NULL,
    acquisition_job_id TEXT NOT NULL,
    job_code TEXT NOT NULL,
    job_name TEXT NOT NULL,
    source_system_id TEXT NOT NULL,
    script_version_id TEXT NOT NULL,
    connection_id TEXT NOT NULL,
    target_dataset_id TEXT NOT NULL,
    topic_table_id TEXT,
    trigger_type TEXT NOT NULL CHECK (trigger_type IN ('manual','schedule','event')),
    schedule_expression TEXT,
    execution_mode TEXT NOT NULL CHECK (execution_mode IN ('realtime','offline')),
    job_config TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','disabled')),
    next_run_at TEXT,
    owner_user_id TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, acquisition_job_id),
    UNIQUE (tenant_id, job_code),
    FOREIGN KEY (tenant_id, source_system_id)
        REFERENCES platform_source_systems(tenant_id, source_system_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, script_version_id)
        REFERENCES platform_acquisition_script_versions(tenant_id, script_version_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, connection_id)
        REFERENCES platform_data_connections(tenant_id, connection_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS platform_acquisition_job_runs (
    tenant_id TEXT NOT NULL,
    acquisition_run_id TEXT NOT NULL,
    acquisition_job_id TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled','repair_review')),
    attempt_no INTEGER NOT NULL DEFAULT 1 CHECK (attempt_no > 0),
    input_cursor TEXT NOT NULL DEFAULT '{}',
    output_cursor TEXT NOT NULL DEFAULT '{}',
    rows_read INTEGER NOT NULL DEFAULT 0 CHECK (rows_read >= 0),
    rows_written INTEGER NOT NULL DEFAULT 0 CHECK (rows_written >= 0),
    source_snapshot TEXT NOT NULL DEFAULT '{}',
    quality_summary TEXT NOT NULL DEFAULT '{}',
    output_artifact_id TEXT,
    partition_id TEXT,
    started_at TEXT,
    finished_at TEXT,
    error_code TEXT,
    error_summary TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, acquisition_run_id),
    UNIQUE (tenant_id, acquisition_job_id, idempotency_key),
    FOREIGN KEY (tenant_id, acquisition_job_id)
        REFERENCES platform_acquisition_jobs(tenant_id, acquisition_job_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS platform_data_artifacts (
    tenant_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL CHECK (artifact_type IN ('csv','parquet','json','image','chart','export','document','other')),
    object_uri TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('uploading','active','quarantined','expired','deleted')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, artifact_id),
    UNIQUE (tenant_id, content_hash, object_uri)
);

CREATE TABLE IF NOT EXISTS platform_dataset_partitions (
    tenant_id TEXT NOT NULL,
    partition_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    topic_table_id TEXT,
    org_unit_id TEXT,
    partition_key TEXT NOT NULL,
    partition_hash TEXT NOT NULL CHECK (length(partition_hash) = 64),
    artifact_id TEXT NOT NULL,
    source_version TEXT,
    snapshot_at TEXT NOT NULL,
    watermark_at TEXT,
    row_count INTEGER NOT NULL CHECK (row_count >= 0),
    data_hash TEXT NOT NULL CHECK (length(data_hash) = 64),
    freshness_status TEXT NOT NULL CHECK (freshness_status IN ('fresh','stale','unknown','blocked')),
    acquisition_run_id TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, partition_id),
    FOREIGN KEY (tenant_id, artifact_id)
        REFERENCES platform_data_artifacts(tenant_id, artifact_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, acquisition_run_id)
        REFERENCES platform_acquisition_job_runs(tenant_id, acquisition_run_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS platform_data_quality_results (
    tenant_id TEXT NOT NULL,
    quality_result_id TEXT NOT NULL,
    acquisition_run_id TEXT NOT NULL,
    partition_id TEXT,
    rule_code TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('passed','warning','failed','error')),
    score REAL CHECK (score >= 0 AND score <= 1),
    observed_value TEXT NOT NULL DEFAULT '{}',
    threshold_value TEXT NOT NULL DEFAULT '{}',
    blocking INTEGER NOT NULL DEFAULT 0 CHECK (blocking IN (0,1)),
    evaluated_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    PRIMARY KEY (tenant_id, quality_result_id),
    FOREIGN KEY (tenant_id, acquisition_run_id)
        REFERENCES platform_acquisition_job_runs(tenant_id, acquisition_run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS platform_acquisition_repair_proposals (
    tenant_id TEXT NOT NULL,
    repair_proposal_id TEXT NOT NULL,
    acquisition_run_id TEXT NOT NULL,
    failed_script_version_id TEXT NOT NULL,
    diagnosis TEXT NOT NULL,
    generation_method TEXT NOT NULL CHECK (generation_method IN ('deterministic','llm','manual')),
    candidate_source_code TEXT,
    candidate_hash TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending','approved','rejected','applied','superseded')),
    reviewed_by TEXT,
    reviewed_at TEXT,
    applied_script_version_id TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, repair_proposal_id),
    FOREIGN KEY (tenant_id, acquisition_run_id)
        REFERENCES platform_acquisition_job_runs(tenant_id, acquisition_run_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, failed_script_version_id)
        REFERENCES platform_acquisition_script_versions(tenant_id, script_version_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS platform_outbox_events (
    tenant_id TEXT NOT NULL,
    outbox_event_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','publishing','published','failed')),
    available_at TEXT NOT NULL,
    published_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, outbox_event_id)
);

CREATE INDEX IF NOT EXISTS idx_acquisition_jobs_due
    ON platform_acquisition_jobs(status, next_run_at);
CREATE INDEX IF NOT EXISTS idx_acquisition_runs_status
    ON platform_acquisition_job_runs(tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dataset_partitions_latest
    ON platform_dataset_partitions(tenant_id, topic_table_id, org_unit_id, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_acquisition_repairs_review
    ON platform_acquisition_repair_proposals(tenant_id, review_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_outbox_pending
    ON platform_outbox_events(status, available_at);
