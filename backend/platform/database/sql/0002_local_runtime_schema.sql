-- SQLite local-development schema. PostgreSQL production structures are
-- generated separately from schema_catalog.py. Store constructors must not be
-- the authoritative schema migration mechanism.

CREATE TABLE IF NOT EXISTS auth_roles (
    role_id TEXT PRIMARY KEY,
    tenant_id TEXT,
    name TEXT NOT NULL,
    level INTEGER NOT NULL CHECK (level BETWEEN 0 AND 100),
    is_system INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0, 1)),
    created_by TEXT
);

CREATE TABLE IF NOT EXISTS auth_role_assignments (
    user_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    role_id TEXT NOT NULL REFERENCES auth_roles(role_id) ON DELETE CASCADE,
    granted_by TEXT,
    PRIMARY KEY (user_id, tenant_id, role_id)
);

CREATE TABLE IF NOT EXISTS auth_permission_policies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id TEXT NOT NULL REFERENCES auth_roles(role_id) ON DELETE CASCADE,
    tenant_id TEXT,
    obj TEXT NOT NULL,
    act TEXT NOT NULL,
    effect TEXT NOT NULL DEFAULT 'allow' CHECK (effect IN ('allow', 'deny')),
    attrs TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(attrs)),
    priority INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS auth_manageable_roles (
    role_id TEXT NOT NULL REFERENCES auth_roles(role_id) ON DELETE CASCADE,
    manageable_role_id TEXT NOT NULL REFERENCES auth_roles(role_id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, manageable_role_id),
    CHECK (role_id <> manageable_role_id)
);

CREATE INDEX IF NOT EXISTS idx_auth_role_assignments_user_tenant
    ON auth_role_assignments(user_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_auth_permission_policies_role
    ON auth_permission_policies(role_id, priority);
CREATE UNIQUE INDEX IF NOT EXISTS uq_auth_permission_policy_identity
    ON auth_permission_policies(
        role_id, COALESCE(tenant_id, '*'), obj, act, effect, attrs, priority
    );

CREATE TABLE IF NOT EXISTS platform_user_profiles (
    user_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    department TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('invited', 'active', 'locked', 'inactive', 'disabled')),
    last_login TEXT NOT NULL DEFAULT '未登录',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_user_profiles_email
    ON platform_user_profiles(lower(email));

CREATE TABLE IF NOT EXISTS platform_analysis_tasks (
    task_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    question TEXT NOT NULL,
    task_type TEXT NOT NULL,
    analysis_plan TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(analysis_plan)),
    plan TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(plan)),
    skill_results TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(skill_results)),
    knowledge_refs TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(knowledge_refs)),
    conclusions TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(conclusions)),
    review TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(review)),
    trace_id TEXT,
    status TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('queued', 'planning', 'running', 'review_required', 'completed', 'failed', 'cancelled')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_platform_analysis_tasks_tenant_user
    ON platform_analysis_tasks(tenant_id, user_id);

CREATE TABLE IF NOT EXISTS platform_knowledge_documents (
    doc_id TEXT PRIMARY KEY,
    tenant_id TEXT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'document',
    domains TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(domains)),
    tags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_platform_knowledge_documents_tenant
    ON platform_knowledge_documents(tenant_id);

CREATE TABLE IF NOT EXISTS platform_data_asset_items (
    tenant_id TEXT NOT NULL,
    item_type TEXT NOT NULL,
    item_id TEXT NOT NULL,
    title TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload)),
    created_by TEXT,
    updated_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, item_type, item_id)
);

CREATE INDEX IF NOT EXISTS idx_platform_data_asset_items_tenant_type
    ON platform_data_asset_items(tenant_id, item_type, updated_at DESC);

CREATE TABLE IF NOT EXISTS platform_application_module_state (
    tenant_id TEXT NOT NULL,
    module_key TEXT NOT NULL,
    state_payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(state_payload)),
    updated_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, module_key)
);

CREATE TABLE IF NOT EXISTS platform_application_actions (
    tenant_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    module_key TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('accepted', 'running', 'completed', 'failed', 'rejected')),
    payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload)),
    result TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(result)),
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, action_id)
);

CREATE INDEX IF NOT EXISTS idx_platform_application_module_state
    ON platform_application_module_state(tenant_id, module_key);
CREATE INDEX IF NOT EXISTS idx_platform_application_actions_tenant_module
    ON platform_application_actions(tenant_id, module_key, created_at DESC);

CREATE TABLE IF NOT EXISTS platform_memory_records (
    memory_id TEXT PRIMARY KEY,
    memory_type TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(content)),
    source_trace_id TEXT,
    confidence REAL NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 1),
    verified_status TEXT NOT NULL DEFAULT 'draft',
    created_by TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_platform_memory_records_tenant_type
    ON platform_memory_records(tenant_id, memory_type);
CREATE INDEX IF NOT EXISTS idx_platform_memory_records_subject
    ON platform_memory_records(subject);

CREATE TABLE IF NOT EXISTS platform_metric_dictionary (
    tenant_id TEXT NOT NULL,
    metric_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload)),
    created_by TEXT,
    updated_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, metric_id)
);

CREATE TABLE IF NOT EXISTS platform_metric_visibility (
    owner_tenant_id TEXT NOT NULL,
    metric_id TEXT NOT NULL,
    visible_tenant_id TEXT NOT NULL,
    visible_role_name TEXT NOT NULL DEFAULT '*',
    PRIMARY KEY (owner_tenant_id, metric_id, visible_tenant_id, visible_role_name),
    FOREIGN KEY (owner_tenant_id, metric_id)
        REFERENCES platform_metric_dictionary(tenant_id, metric_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_platform_metric_dictionary_tenant
    ON platform_metric_dictionary(tenant_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_metric_dictionary_name
    ON platform_metric_dictionary(tenant_id, metric_name);
CREATE INDEX IF NOT EXISTS idx_platform_metric_visibility_lookup
    ON platform_metric_visibility(visible_tenant_id, visible_role_name);

CREATE TABLE IF NOT EXISTS platform_model_integrations (
    tenant_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload)),
    created_by TEXT,
    updated_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, model_id)
);

CREATE TABLE IF NOT EXISTS platform_speech_integrations (
    tenant_id TEXT NOT NULL,
    integration_id TEXT NOT NULL,
    integration_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload)),
    created_by TEXT,
    updated_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, integration_id)
);

CREATE TABLE IF NOT EXISTS platform_data_connections (
    tenant_id TEXT NOT NULL,
    connection_id TEXT NOT NULL,
    institution TEXT NOT NULL,
    account TEXT NOT NULL,
    secret_value TEXT NOT NULL,
    dataset TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload)),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'testing', 'verified', 'degraded', 'disabled', 'connected', 'mock')),
    created_by TEXT,
    updated_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, connection_id)
);

CREATE TABLE IF NOT EXISTS platform_system_data_params (
    tenant_id TEXT NOT NULL,
    param_id TEXT NOT NULL,
    param_name TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload)),
    created_by TEXT,
    updated_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, param_id)
);

CREATE INDEX IF NOT EXISTS idx_platform_model_integrations_tenant
    ON platform_model_integrations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_platform_speech_integrations_tenant
    ON platform_speech_integrations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_platform_data_connections_tenant
    ON platform_data_connections(tenant_id);
CREATE INDEX IF NOT EXISTS idx_platform_system_data_params_tenant
    ON platform_system_data_params(tenant_id);

CREATE TABLE IF NOT EXISTS platform_weekly_report_versions (
    tenant_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    report_id TEXT NOT NULL,
    name TEXT NOT NULL,
    saved_at TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload)),
    created_by TEXT,
    updated_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, version_id)
);

CREATE TABLE IF NOT EXISTS platform_report_comments (
    tenant_id TEXT NOT NULL,
    report_id TEXT NOT NULL,
    comments TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(comments)),
    updated_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, report_id)
);

CREATE TABLE IF NOT EXISTS platform_saved_analysis_results (
    tenant_id TEXT NOT NULL,
    result_id TEXT NOT NULL,
    title TEXT NOT NULL,
    query_text TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload)),
    created_by TEXT,
    updated_by TEXT,
    saved_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, result_id)
);

CREATE TABLE IF NOT EXISTS weekly_report_ai_analysis_task (
    tenant_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    input_snapshot TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(input_snapshot)),
    debate_result TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(debate_result)),
    final_result TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(final_result)),
    error_message TEXT,
    created_by TEXT,
    updated_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, version_id)
);

CREATE INDEX IF NOT EXISTS idx_platform_weekly_report_versions_tenant
    ON platform_weekly_report_versions(tenant_id, saved_at DESC);
CREATE INDEX IF NOT EXISTS idx_platform_report_comments_tenant
    ON platform_report_comments(tenant_id, report_id);
CREATE INDEX IF NOT EXISTS idx_platform_saved_analysis_results_tenant
    ON platform_saved_analysis_results(tenant_id, saved_at DESC);
CREATE INDEX IF NOT EXISTS idx_weekly_report_ai_analysis_task_tenant
    ON weekly_report_ai_analysis_task(tenant_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS platform_audit_events (
    event_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    actor_user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(detail)),
    ip_address TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_platform_audit_events_tenant_created
    ON platform_audit_events(tenant_id, created_at);

CREATE TABLE IF NOT EXISTS platform_runtime_events (
    event_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok', 'degraded', 'error')),
    latency_ms INTEGER NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
    fallback_used INTEGER NOT NULL DEFAULT 0 CHECK (fallback_used IN (0, 1)),
    detail TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(detail)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS platform_trace_spans (
    span_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    span_name TEXT NOT NULL,
    inputs TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(inputs)),
    outputs TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(outputs)),
    status TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'error')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (trace_id, span_id)
);

CREATE INDEX IF NOT EXISTS idx_platform_runtime_events_created
    ON platform_runtime_events(created_at);
CREATE INDEX IF NOT EXISTS idx_platform_trace_spans_trace
    ON platform_trace_spans(trace_id);
