-- Per-run LLM usage logging (Cursor Cloud Agents), attributed to Minion users

CREATE TABLE IF NOT EXISTS llm_usage_events (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id INTEGER REFERENCES chat_threads(id) ON DELETE SET NULL,
    session_id INTEGER REFERENCES studio_sessions(id) ON DELETE SET NULL,
    cursor_agent_id VARCHAR(64) NOT NULL,
    cursor_run_id VARCHAR(64) NOT NULL UNIQUE,
    model VARCHAR(80),
    source VARCHAR(80) NOT NULL DEFAULT 'chat',
    run_status VARCHAR(32),
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd NUMERIC(12, 6) NOT NULL DEFAULT 0,
    billed_usd NUMERIC(12, 6) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_llm_usage_events_user_created
    ON llm_usage_events (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_llm_usage_events_user_period
    ON llm_usage_events (user_id, created_at);

ALTER TABLE llm_usage_events ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON llm_usage_events FROM anon, authenticated;
REVOKE ALL ON SEQUENCE llm_usage_events_id_seq FROM anon, authenticated;
