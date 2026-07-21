-- Licensed market observations and auditable monitoring events.

CREATE TABLE IF NOT EXISTS platform_market_sources (
    tenant_id TEXT NOT NULL,
    market_source_id TEXT NOT NULL,
    source_system_id TEXT NOT NULL,
    source_url TEXT,
    publisher TEXT NOT NULL,
    acquisition_method TEXT NOT NULL CHECK (acquisition_method IN ('api','database','file','licensed_feed','manual_review')),
    license_type TEXT NOT NULL,
    reliability_score REAL NOT NULL CHECK (reliability_score >= 0 AND reliability_score <= 1),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','expired','disabled')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, market_source_id),
    FOREIGN KEY (tenant_id, source_system_id)
        REFERENCES platform_source_systems(tenant_id, source_system_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS platform_market_entities (
    tenant_id TEXT NOT NULL,
    market_entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('institution','product','industry','region','index','event_subject')),
    entity_code TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '[]',
    attributes TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','merged','inactive')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, market_entity_id),
    UNIQUE (tenant_id, entity_code)
);

CREATE TABLE IF NOT EXISTS platform_market_observations (
    tenant_id TEXT NOT NULL,
    market_observation_id TEXT NOT NULL,
    market_source_id TEXT NOT NULL,
    market_entity_id TEXT NOT NULL,
    metric_code TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    value_numeric REAL,
    value_text TEXT,
    unit TEXT,
    currency TEXT,
    evidence_artifact_id TEXT NOT NULL,
    source_record_id TEXT,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, market_observation_id),
    UNIQUE (tenant_id, market_source_id, source_record_id, metric_code),
    CHECK (value_numeric IS NOT NULL OR value_text IS NOT NULL),
    FOREIGN KEY (tenant_id, market_source_id)
        REFERENCES platform_market_sources(tenant_id, market_source_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, market_entity_id)
        REFERENCES platform_market_entities(tenant_id, market_entity_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, evidence_artifact_id)
        REFERENCES platform_data_artifacts(tenant_id, artifact_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS platform_market_monitoring_rules (
    tenant_id TEXT NOT NULL,
    market_rule_id TEXT NOT NULL,
    rule_name TEXT NOT NULL,
    entity_selector TEXT NOT NULL,
    metric_code TEXT NOT NULL,
    condition_expression TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info','warning','error','critical')),
    cooldown_seconds INTEGER NOT NULL DEFAULT 3600 CHECK (cooldown_seconds >= 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('draft','active','paused','disabled')),
    owner_user_id TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, market_rule_id)
);

CREATE TABLE IF NOT EXISTS platform_market_monitoring_events (
    tenant_id TEXT NOT NULL,
    market_event_id TEXT NOT NULL,
    market_rule_id TEXT NOT NULL,
    market_entity_id TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','resolved','suppressed')),
    event_summary TEXT NOT NULL,
    evidence TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    acknowledged_by TEXT,
    resolved_at TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, market_event_id),
    UNIQUE (tenant_id, market_rule_id, observation_id),
    FOREIGN KEY (tenant_id, market_rule_id)
        REFERENCES platform_market_monitoring_rules(tenant_id, market_rule_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, market_entity_id)
        REFERENCES platform_market_entities(tenant_id, market_entity_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, observation_id)
        REFERENCES platform_market_observations(tenant_id, market_observation_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_market_observation_latest
    ON platform_market_observations(tenant_id, market_entity_id, metric_code, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_market_event_status
    ON platform_market_monitoring_events(tenant_id, status, detected_at DESC);
