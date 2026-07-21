-- Local runtime parity for the governed Yushu/browser crawler integration.

PRAGMA legacy_alter_table = ON;
ALTER TABLE platform_acquisition_scripts RENAME TO platform_acquisition_scripts_0024_old;

CREATE TABLE platform_acquisition_scripts (
    tenant_id TEXT NOT NULL,
    acquisition_script_id TEXT NOT NULL,
    script_code TEXT NOT NULL,
    script_name TEXT NOT NULL,
    runtime TEXT NOT NULL CHECK (runtime IN ('python','sql','http','browser','shell_restricted')),
    current_version_no INTEGER NOT NULL DEFAULT 0 CHECK (current_version_no >= 0),
    owner_user_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'review' CHECK (status IN ('draft','review','active','degraded','disabled')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, acquisition_script_id),
    UNIQUE (tenant_id, script_code)
);

INSERT INTO platform_acquisition_scripts(
    tenant_id, acquisition_script_id, script_code, script_name, runtime,
    current_version_no, owner_user_id, status, created_by, created_at, updated_at
)
SELECT tenant_id, acquisition_script_id, script_code, script_name, runtime,
       current_version_no, owner_user_id, status, created_by, created_at, updated_at
FROM platform_acquisition_scripts_0024_old;

DROP TABLE platform_acquisition_scripts_0024_old;
PRAGMA legacy_alter_table = OFF;

CREATE TABLE IF NOT EXISTS platform_topic_tables (
    tenant_id TEXT NOT NULL,
    topic_table_id TEXT NOT NULL,
    topic_code TEXT NOT NULL,
    topic_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    current_version_no INTEGER NOT NULL DEFAULT 1,
    query_template TEXT NOT NULL,
    query_hash TEXT NOT NULL,
    freshness_sla_seconds INTEGER,
    status TEXT NOT NULL DEFAULT 'published',
    validated_at TEXT,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, topic_table_id),
    UNIQUE (tenant_id, topic_code)
);

CREATE TABLE IF NOT EXISTS platform_topic_table_fields (
    tenant_id TEXT NOT NULL,
    topic_field_id TEXT NOT NULL,
    topic_table_id TEXT NOT NULL,
    field_code TEXT NOT NULL,
    field_name TEXT NOT NULL,
    data_type TEXT NOT NULL,
    ordinal_position INTEGER NOT NULL,
    source_expression TEXT NOT NULL,
    is_dimension INTEGER NOT NULL DEFAULT 0,
    is_measure INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, topic_field_id),
    UNIQUE (tenant_id, topic_table_id, field_code),
    FOREIGN KEY (tenant_id, topic_table_id)
        REFERENCES platform_topic_tables(tenant_id, topic_table_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS platform_datasets (
    tenant_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    connection_id TEXT NOT NULL,
    dataset_code TEXT NOT NULL,
    dataset_name TEXT NOT NULL,
    physical_locator TEXT NOT NULL DEFAULT '{}',
    dataset_type TEXT NOT NULL DEFAULT 'table',
    data_classification TEXT NOT NULL DEFAULT 'internal',
    freshness_sla_seconds INTEGER,
    status TEXT NOT NULL DEFAULT 'active',
    schema_hash TEXT,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, dataset_id),
    UNIQUE (tenant_id, dataset_code),
    FOREIGN KEY (tenant_id, connection_id)
        REFERENCES platform_data_connections(tenant_id, connection_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS platform_dataset_fields (
    tenant_id TEXT NOT NULL,
    field_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    field_code TEXT NOT NULL,
    field_name TEXT NOT NULL,
    ordinal_position INTEGER NOT NULL,
    physical_type TEXT NOT NULL,
    semantic_type TEXT,
    is_nullable INTEGER NOT NULL DEFAULT 1,
    is_dimension INTEGER NOT NULL DEFAULT 0,
    is_measure INTEGER NOT NULL DEFAULT 0,
    classification TEXT NOT NULL DEFAULT 'internal',
    masking_policy TEXT NOT NULL DEFAULT '{}',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, field_id),
    UNIQUE (tenant_id, dataset_id, field_code),
    FOREIGN KEY (tenant_id, dataset_id)
        REFERENCES platform_datasets(tenant_id, dataset_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS platform_topic_table_sources (
    tenant_id TEXT NOT NULL,
    topic_table_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    source_alias TEXT NOT NULL,
    join_role TEXT NOT NULL DEFAULT 'primary',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, topic_table_id, dataset_id),
    FOREIGN KEY (tenant_id, topic_table_id)
        REFERENCES platform_topic_tables(tenant_id, topic_table_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, dataset_id)
        REFERENCES platform_datasets(tenant_id, dataset_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_local_datasets_connection
    ON platform_datasets(tenant_id, connection_id, status);
CREATE INDEX IF NOT EXISTS idx_local_topic_sources
    ON platform_topic_table_sources(tenant_id, topic_table_id);
