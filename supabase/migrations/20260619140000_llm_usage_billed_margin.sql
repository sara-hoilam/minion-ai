-- Add billed_usd (actual API cost + 40% Minion margin) to LLM usage events

ALTER TABLE llm_usage_events
    ADD COLUMN IF NOT EXISTS billed_usd NUMERIC(12, 6) NOT NULL DEFAULT 0;

-- Backfill: prior rows stored cost without margin; treat stored cost as actual API cost
UPDATE llm_usage_events
SET billed_usd = ROUND(cost_usd / 0.60, 6)
WHERE billed_usd = 0 AND cost_usd > 0;
