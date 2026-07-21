-- Immutable report snapshots, evidence gates, optimistic comment revisions and
-- reviewable learning candidates.

ALTER TABLE platform_weekly_report_versions ADD COLUMN owner_user_id TEXT;
ALTER TABLE platform_weekly_report_versions ADD COLUMN content_hash TEXT;
ALTER TABLE platform_weekly_report_versions ADD COLUMN parent_version_id TEXT;
ALTER TABLE platform_weekly_report_versions ADD COLUMN revision_no INTEGER NOT NULL DEFAULT 1;
ALTER TABLE platform_weekly_report_versions ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'saved';
ALTER TABLE platform_weekly_report_versions ADD COLUMN publication_status TEXT NOT NULL DEFAULT 'review_required';
ALTER TABLE platform_weekly_report_versions ADD COLUMN evidence_summary TEXT NOT NULL DEFAULT '{}';

CREATE UNIQUE INDEX IF NOT EXISTS uq_weekly_report_version_content
    ON platform_weekly_report_versions(tenant_id, report_id, content_hash);
CREATE INDEX IF NOT EXISTS idx_weekly_report_owner
    ON platform_weekly_report_versions(tenant_id, owner_user_id, saved_at DESC);

CREATE TABLE IF NOT EXISTS platform_report_comment_revisions (
    tenant_id TEXT NOT NULL,
    report_id TEXT NOT NULL,
    revision_no INTEGER NOT NULL CHECK (revision_no > 0),
    comments_snapshot TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL CHECK (length(snapshot_hash) = 64),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, report_id, revision_no)
);

CREATE TABLE IF NOT EXISTS platform_report_learning_candidates (
    tenant_id TEXT NOT NULL,
    learning_candidate_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    candidate_type TEXT NOT NULL CHECK (candidate_type IN ('analysis_method','behavior_habit','todo','business_fact')),
    candidate_content TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    evidence_summary TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    status TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate','review','approved','rejected','applied')),
    reviewed_by TEXT,
    reviewed_at TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, learning_candidate_id),
    UNIQUE (tenant_id, version_id, candidate_type, content_hash),
    FOREIGN KEY (tenant_id, version_id)
        REFERENCES platform_weekly_report_versions(tenant_id, version_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_report_learning_review
    ON platform_report_learning_candidates(tenant_id, status, created_at DESC);
