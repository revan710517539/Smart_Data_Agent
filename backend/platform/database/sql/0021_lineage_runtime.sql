CREATE TABLE IF NOT EXISTS platform_lineage_edges (
    lineage_edge_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    edge_type TEXT NOT NULL CHECK (edge_type IN ('reads','derives','aggregates','references','publishes','generates')),
    expression_hash TEXT NOT NULL DEFAULT '' CHECK (expression_hash = '' OR length(expression_hash) = 64),
    confidence REAL NOT NULL DEFAULT 1 CHECK (confidence >= 0 AND confidence <= 1),
    metadata TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, source_type, source_id, target_type, target_id, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_platform_lineage_source
    ON platform_lineage_edges(tenant_id, source_type, source_id, created_at);
CREATE INDEX IF NOT EXISTS idx_platform_lineage_target
    ON platform_lineage_edges(tenant_id, target_type, target_id, created_at);
