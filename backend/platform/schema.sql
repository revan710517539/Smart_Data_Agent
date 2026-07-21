-- Platform schema for Semantic Data Agent architecture.
-- Authorization tables stay in backend/authz/schema.sql.

CREATE TABLE IF NOT EXISTS platform_agents (
    agent_id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    description TEXT,
    prompt_template_id TEXT,
    allowed_skills JSONB NOT NULL DEFAULT '[]'::jsonb,
    allowed_datasets JSONB NOT NULL DEFAULT '[]'::jsonb,
    model_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    memory_policy TEXT NOT NULL DEFAULT 'read_write_reviewed',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS platform_agent_groups (
    group_id TEXT PRIMARY KEY,
    group_name TEXT NOT NULL,
    mission TEXT NOT NULL,
    controller_agent_id TEXT NOT NULL,
    source_file TEXT,
    stage_gates JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS platform_agent_group_members (
    id BIGSERIAL PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES platform_agent_groups(group_id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES platform_agents(agent_id) ON DELETE CASCADE,
    role_in_group TEXT NOT NULL DEFAULT 'member',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (group_id, agent_id)
);

CREATE TABLE IF NOT EXISTS platform_skills (
    skill_id TEXT PRIMARY KEY,
    skill_name TEXT NOT NULL,
    skill_type TEXT NOT NULL,
    description TEXT,
    input_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    runtime_type TEXT NOT NULL,
    endpoint TEXT,
    mcp_server_id TEXT,
    permission_scope JSONB NOT NULL DEFAULT '[]'::jsonb,
    risk_level TEXT NOT NULL DEFAULT 'medium',
    timeout_seconds INTEGER NOT NULL DEFAULT 60,
    retry_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    version TEXT NOT NULL DEFAULT '1.0.0',
    owner TEXT NOT NULL DEFAULT 'data-platform',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS platform_mcp_servers (
    server_id TEXT PRIMARY KEY,
    server_name TEXT NOT NULL,
    server_type TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    auth_type TEXT NOT NULL DEFAULT 'none',
    exposed_tools JSONB NOT NULL DEFAULT '[]'::jsonb,
    allowed_agents JSONB NOT NULL DEFAULT '[]'::jsonb,
    health_status TEXT NOT NULL DEFAULT 'unknown',
    owner TEXT NOT NULL DEFAULT 'data-platform',
    risk_level TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS platform_knowledge_documents (
    doc_id TEXT PRIMARY KEY,
    tenant_id TEXT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_uri TEXT,
    domains JSONB NOT NULL DEFAULT '[]'::jsonb,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    embedding_id TEXT,
    verified_status TEXT NOT NULL DEFAULT 'draft',
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS platform_memory_records (
    memory_id TEXT PRIMARY KEY,
    memory_type TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    content JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding_id TEXT,
    graph_entity_id TEXT,
    source_trace_id TEXT,
    confidence NUMERIC(5, 4) NOT NULL DEFAULT 0,
    verified_status TEXT NOT NULL DEFAULT 'draft',
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS platform_metric_dictionary (
    tenant_id TEXT NOT NULL,
    metric_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT,
    updated_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, metric_id),
    UNIQUE (tenant_id, metric_name)
);

CREATE TABLE IF NOT EXISTS platform_model_integrations (
    tenant_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT,
    updated_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, model_id)
);

CREATE TABLE IF NOT EXISTS platform_data_connections (
    tenant_id TEXT NOT NULL,
    connection_id TEXT NOT NULL,
    institution TEXT NOT NULL,
    account TEXT NOT NULL,
    secret_value TEXT NOT NULL,
    dataset TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'connected',
    created_by TEXT,
    updated_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, connection_id)
);

CREATE TABLE IF NOT EXISTS platform_system_data_params (
    tenant_id TEXT NOT NULL,
    param_id TEXT NOT NULL,
    param_name TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT,
    updated_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, param_id)
);

CREATE TABLE IF NOT EXISTS platform_data_asset_items (
    tenant_id TEXT NOT NULL,
    item_type TEXT NOT NULL,
    item_id TEXT NOT NULL,
    title TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT,
    updated_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, item_type, item_id)
);

CREATE TABLE IF NOT EXISTS platform_audit_events (
    event_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    actor_user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL DEFAULT '',
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    ip_address TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS platform_analysis_tasks (
    task_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    question TEXT NOT NULL,
    task_type TEXT NOT NULL,
    plan JSONB NOT NULL DEFAULT '[]'::jsonb,
    skill_results JSONB NOT NULL DEFAULT '[]'::jsonb,
    knowledge_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    graph_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    conclusions JSONB NOT NULL DEFAULT '[]'::jsonb,
    trace_id TEXT,
    status TEXT NOT NULL DEFAULT 'created',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS platform_trace_spans (
    span_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    span_name TEXT NOT NULL,
    inputs JSONB NOT NULL DEFAULT '{}'::jsonb,
    outputs JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'ok',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS platform_model_registry (
    model_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    endpoint TEXT,
    capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    context_window INTEGER NOT NULL,
    cost_level TEXT NOT NULL DEFAULT 'medium',
    latency_level TEXT NOT NULL DEFAULT 'medium',
    data_policy TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS platform_prompt_templates (
    prompt_id TEXT PRIMARY KEY,
    prompt_name TEXT NOT NULL,
    prompt_type TEXT NOT NULL,
    agent_id TEXT,
    template_content TEXT NOT NULL,
    variables JSONB NOT NULL DEFAULT '[]'::jsonb,
    version TEXT NOT NULL DEFAULT '1.0.0',
    status TEXT NOT NULL DEFAULT 'active',
    owner TEXT NOT NULL DEFAULT 'data-platform',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS platform_evaluations (
    eval_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    task_id TEXT,
    task_type TEXT NOT NULL,
    sql_correctness_score NUMERIC(5, 4),
    answer_faithfulness_score NUMERIC(5, 4),
    citation_score NUMERIC(5, 4),
    business_quality_score NUMERIC(5, 4),
    agent_plan_score NUMERIC(5, 4),
    permission_compliance_score NUMERIC(5, 4),
    latency_ms INTEGER,
    cost_amount NUMERIC(12, 4),
    user_feedback TEXT,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_platform_memory_tenant_type
    ON platform_memory_records (tenant_id, memory_type);

CREATE INDEX IF NOT EXISTS idx_platform_metric_dictionary_tenant
    ON platform_metric_dictionary (tenant_id);

CREATE INDEX IF NOT EXISTS idx_platform_model_integrations_tenant
    ON platform_model_integrations (tenant_id);

CREATE INDEX IF NOT EXISTS idx_platform_data_connections_tenant
    ON platform_data_connections (tenant_id);

CREATE INDEX IF NOT EXISTS idx_platform_system_data_params_tenant
    ON platform_system_data_params (tenant_id);

CREATE INDEX IF NOT EXISTS idx_platform_data_asset_items_tenant_type
    ON platform_data_asset_items (tenant_id, item_type, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_platform_audit_events_tenant_created
    ON platform_audit_events (tenant_id, created_at);

CREATE INDEX IF NOT EXISTS idx_platform_knowledge_tenant
    ON platform_knowledge_documents (tenant_id);

CREATE INDEX IF NOT EXISTS idx_platform_tasks_tenant_user
    ON platform_analysis_tasks (tenant_id, user_id);

CREATE INDEX IF NOT EXISTS idx_platform_trace_spans_trace
    ON platform_trace_spans (trace_id);

CREATE INDEX IF NOT EXISTS idx_platform_agent_group_members_group
    ON platform_agent_group_members (group_id);

CREATE INDEX IF NOT EXISTS idx_platform_evaluations_trace
    ON platform_evaluations (trace_id);
