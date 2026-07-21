-- Replace mutable runtime-memory rows with evidence-backed lifecycle records.

ALTER TABLE platform_memory_records RENAME TO platform_memory_records_legacy;

CREATE TABLE platform_memory_records (
    tenant_id TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    memory_type TEXT NOT NULL CHECK (memory_type IN ('analysis_case','behavior_habit','business_fact','preference','warning','other')),
    subject_type TEXT NOT NULL CHECK (subject_type IN ('user','role','org','tenant')),
    subject_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    status TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate','review','active','superseded','expired','rejected')),
    confidence REAL NOT NULL DEFAULT 0 CHECK (confidence >= 0 AND confidence <= 1),
    weight REAL NOT NULL DEFAULT 1 CHECK (weight >= 0),
    valid_from TEXT NOT NULL,
    expires_at TEXT,
    supersedes_memory_id TEXT,
    source_trace_id TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, memory_id),
    FOREIGN KEY (tenant_id, supersedes_memory_id)
        REFERENCES platform_memory_records(tenant_id, memory_id) ON DELETE SET NULL
);

CREATE TABLE platform_memory_evidence (
    tenant_id TEXT NOT NULL,
    memory_evidence_id TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    evidence_hash TEXT NOT NULL CHECK (length(evidence_hash) = 64),
    support_type TEXT NOT NULL DEFAULT 'supports' CHECK (support_type IN ('supports','contradicts','context')),
    created_by TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, memory_evidence_id),
    UNIQUE (tenant_id, memory_id, evidence_type, evidence_id),
    FOREIGN KEY (tenant_id, memory_id)
        REFERENCES platform_memory_records(tenant_id, memory_id) ON DELETE CASCADE
);

CREATE TABLE platform_memory_reviews (
    tenant_id TEXT NOT NULL,
    memory_review_id TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    reviewer_user_id TEXT,
    review_type TEXT NOT NULL CHECK (review_type IN ('human','automated')),
    decision TEXT NOT NULL CHECK (decision IN ('approve','reject','request_change','supersede','expire')),
    comments TEXT NOT NULL DEFAULT '',
    review_evidence TEXT NOT NULL DEFAULT '{}',
    reviewed_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, memory_review_id),
    FOREIGN KEY (tenant_id, memory_id)
        REFERENCES platform_memory_records(tenant_id, memory_id) ON DELETE CASCADE
);

CREATE INDEX idx_memory_recall
    ON platform_memory_records(tenant_id, subject_type, subject_id, memory_type, status, valid_from DESC);
CREATE INDEX idx_memory_hash
    ON platform_memory_records(tenant_id, content_hash);
CREATE INDEX idx_memory_reviews_memory
    ON platform_memory_reviews(tenant_id, memory_id, reviewed_at DESC);
