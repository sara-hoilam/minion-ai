"""Subscription plan definitions and token allowance rules."""

from __future__ import annotations

import os
from dataclasses import dataclass

TOKEN_ALLOWANCE_RATIO = 0.60
TOKENS_PER_USD = 100_000


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    price_usd: int
    description: str
    stripe_price_env: str

    @property
    def monthly_token_usd(self) -> float:
        return round(self.price_usd * TOKEN_ALLOWANCE_RATIO, 2)

    @property
    def monthly_token_count(self) -> int:
        return int(self.monthly_token_usd * TOKENS_PER_USD)

    def stripe_price_id(self) -> str:
        return _stripe_config(self.stripe_price_env)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "price_usd": self.price_usd,
            "price_display": f"${self.price_usd}",
            "monthly_token_usd": self.monthly_token_usd,
            "monthly_token_count": self.monthly_token_count,
            "description": self.description,
            "stripe_configured": bool(self.stripe_price_id()),
        }


PLANS: dict[str, Plan] = {
    p.id: p
    for p in [
        Plan("starter", "Starter", 10, "For individuals exploring agent workflows", "STRIPE_PRICE_STARTER"),
        Plan("growth", "Growth", 25, "For power users running agents daily", "STRIPE_PRICE_GROWTH"),
        Plan("professional", "Professional", 60, "For teams with heavier automation", "STRIPE_PRICE_PROFESSIONAL"),
        Plan("business", "Business", 150, "For departments scaling AI agents", "STRIPE_PRICE_BUSINESS"),
    ]
}

PLAN_ORDER = ["starter", "growth", "professional", "business"]


def get_plan(plan_id: str | None) -> Plan | None:
    if not plan_id:
        return None
    return PLANS.get(plan_id)


def upgrade_token_credit_usd(from_plan_id: str, to_plan_id: str) -> float:
    """Top-up token credit when upgrading mid-cycle: 60% of price difference."""
    from_plan = get_plan(from_plan_id)
    to_plan = get_plan(to_plan_id)
    if not from_plan or not to_plan:
        return 0.0
    diff = max(0, to_plan.price_usd - from_plan.price_usd)
    return round(diff * TOKEN_ALLOWANCE_RATIO, 2)


def _stripe_config(key: str) -> str:
    try:
        from flask import has_app_context, current_app

        if has_app_context():
            val = current_app.config.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
    except RuntimeError:
        pass
    return (os.getenv(key) or "").strip()


def stripe_enabled() -> bool:
    if not _stripe_config("STRIPE_SECRET_KEY"):
        return False
    return any(_stripe_config(p.stripe_price_env) for p in PLANS.values())
