CREATE TABLE IF NOT EXISTS platform_oidc_transactions (
    transaction_id TEXT PRIMARY KEY,
    state_hash TEXT NOT NULL UNIQUE,
    nonce TEXT NOT NULL,
    code_verifier_secret TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    consumed_at INTEGER,
    CHECK (expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS idx_platform_oidc_transactions_expiry
    ON platform_oidc_transactions(expires_at, consumed_at);
