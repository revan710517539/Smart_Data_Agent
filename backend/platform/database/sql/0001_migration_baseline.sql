-- Establish the explicit migration baseline. Domain tables are added by the
-- production foundation migration generated from the reviewed schema catalog.
CREATE TABLE IF NOT EXISTS platform_bootstrap_state (
    state_key TEXT PRIMARY KEY,
    state_value TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO platform_bootstrap_state(state_key, state_value, updated_at)
VALUES ('migration_baseline', '1', CURRENT_TIMESTAMP);
