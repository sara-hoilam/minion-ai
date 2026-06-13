-- Align active subscription budgets with full plan price (billed cap incl. 40% margin)

UPDATE user_subscriptions SET token_budget_usd = 10
WHERE plan_id = 'starter' AND status IN ('active', 'trialing') AND token_budget_usd < 10;

UPDATE user_subscriptions SET token_budget_usd = 25
WHERE plan_id = 'growth' AND status IN ('active', 'trialing') AND token_budget_usd < 25;

UPDATE user_subscriptions SET token_budget_usd = 60
WHERE plan_id = 'professional' AND status IN ('active', 'trialing') AND token_budget_usd < 60;

UPDATE user_subscriptions SET token_budget_usd = 150
WHERE plan_id = 'business' AND status IN ('active', 'trialing') AND token_budget_usd < 150;
