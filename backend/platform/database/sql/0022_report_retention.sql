ALTER TABLE platform_saved_analysis_results ADD COLUMN archived_at TEXT;
ALTER TABLE platform_weekly_report_versions ADD COLUMN archived_at TEXT;

CREATE INDEX IF NOT EXISTS idx_platform_saved_analysis_results_active
    ON platform_saved_analysis_results(tenant_id, archived_at, saved_at DESC);
CREATE INDEX IF NOT EXISTS idx_platform_weekly_report_versions_active
    ON platform_weekly_report_versions(tenant_id, archived_at, saved_at DESC);
