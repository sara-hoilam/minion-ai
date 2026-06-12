"""Subscription plan definitions and token allowance rules."""

from __future__ import annotations

import os
from dataclasses import dataclass

TOKEN_ALLOWANCE_RATIO = 0.60


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

    def stripe_price_id(self) -> str:
        return (os.getenv(self.stripe_price_env) or "").strip()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "price_usd": self.price_usd,
            "price_display": f"${self.price_usd}",
            "monthly_token_usd": self.monthly_token_usd,
            "token_allowance_pct": int(TOKEN_ALLOWANCE_RATIO * 100),
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


def stripe_enabled() -> bool:
    return bool(os.getenv("STRIPE_SECRET_KEY", "").strip()) and any(
        p.stripe_price_id() for p in PLANS.values()
    )
