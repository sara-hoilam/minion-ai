-- Subscription billing and token allowance tracking

CREATE TABLE IF NOT EXISTS user_subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    plan_id VARCHAR(50) NOT NULL DEFAULT 'starter',
    stripe_subscription_id VARCHAR(255),
    stripe_price_id VARCHAR(255),
    status VARCHAR(50) NOT NULL DEFAULT 'inactive',
    token_budget_usd NUMERIC(12, 4) NOT NULL DEFAULT 0,
    token_used_usd NUMERIC(12, 4) NOT NULL DEFAULT 0,
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    cancelled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_user_subscriptions_stripe_sub
    ON user_subscriptions (stripe_subscription_id);

CREATE TABLE IF NOT EXISTS billing_events (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    event_type VARCHAR(80) NOT NULL,
    plan_id VARCHAR(50),
    amount_usd NUMERIC(10, 2),
    token_delta_usd NUMERIC(12, 4),
    stripe_event_id VARCHAR(255) UNIQUE,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_billing_events_user_created
    ON billing_events (user_id, created_at DESC);

ALTER TABLE user_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_events ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON user_subscriptions FROM anon, authenticated;
REVOKE ALL ON billing_events FROM anon, authenticated;
REVOKE ALL ON SEQUENCE user_subscriptions_id_seq FROM anon, authenticated;
REVOKE ALL ON SEQUENCE billing_events_id_seq FROM anon, authenticated;
