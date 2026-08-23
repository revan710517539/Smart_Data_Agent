CREATE TABLE IF NOT EXISTS platform_schema_migration_attempts (
    attempt_id CHAR(36) PRIMARY KEY,
    version VARCHAR(32) NOT NULL,
    name VARCHAR(200) NOT NULL,
    checksum CHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL,
    statement_count INTEGER NOT NULL DEFAULT 0,
    last_statement_index INTEGER NOT NULL DEFAULT 0,
    error_code VARCHAR(160) NULL,
    error_summary VARCHAR(500) NULL,
    started_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    finished_at DATETIME(6) NULL,
    execution_ms INTEGER NOT NULL DEFAULT 0,
    runner_revision CHAR(40) NOT NULL DEFAULT '',
    INDEX idx_platform_schema_migration_attempts_version_started (version, started_at),
    INDEX idx_platform_schema_migration_attempts_status_started (status, started_at),
    CONSTRAINT chk_platform_schema_migration_attempts_status
        CHECK (status IN ('running', 'succeeded', 'failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
