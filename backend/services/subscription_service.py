"""User subscription lifecycle and token allowance accounting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import current_app

from backend.models import BillingEvent, User, UserSubscription, db
from backend.services.billing_plans import (
    TOKEN_ALLOWANCE_RATIO,
    TOKENS_PER_USD,
    get_plan,
    stripe_enabled,
    upgrade_token_credit_usd,
)

ACTIVE_STATUSES = frozenset({"active", "trialing"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def log_event(
    user_id: int | None,
    event_type: str,
    *,
    plan_id: str | None = None,
    amount_usd: float | None = None,
    token_delta_usd: float | None = None,
    stripe_event_id: str | None = None,
    payload: dict | None = None,
) -> None:
    if stripe_event_id:
        existing = BillingEvent.query.filter_by(stripe_event_id=stripe_event_id).first()
        if existing:
            return
    db.session.add(BillingEvent(
        user_id=user_id,
        event_type=event_type,
        plan_id=plan_id,
        amount_usd=amount_usd,
        token_delta_usd=token_delta_usd,
        stripe_event_id=stripe_event_id,
        payload=payload,
    ))


def get_subscription(user: User) -> UserSubscription | None:
    return UserSubscription.query.filter_by(user_id=user.id).first()


def get_or_create_subscription(user: User) -> UserSubscription:
    sub = get_subscription(user)
    if sub:
        return sub
    sub = UserSubscription(user_id=user.id, status="inactive", plan_id="starter")
    db.session.add(sub)
    db.session.flush()
    return sub


def subscription_access_granted(sub: UserSubscription | None) -> bool:
    if current_app.config.get("DISABLE_AUTH"):
        return True
    if not sub or sub.status not in ACTIVE_STATUSES:
        return False
    if stripe_enabled() and not sub.stripe_subscription_id:
        return False
    end = _as_aware(sub.current_period_end)
    if end and _now() > end and not sub.cancel_at_period_end:
        return False
    return True


def subscription_to_dict(sub: UserSubscription | None, user: User) -> dict:
    plan = get_plan(sub.plan_id if sub else None)
    access = subscription_access_granted(sub)
    return {
        "access_granted": access,
        "status": sub.status if sub else "none",
        "plan_id": sub.plan_id if sub else None,
        "plan_name": plan.name if plan else None,
        "price_usd": plan.price_usd if plan else None,
        "token_budget_usd": float(sub.token_budget_usd or 0) if sub else 0,
        "token_used_usd": float(sub.token_used_usd or 0) if sub else 0,
        "token_remaining_usd": sub.token_remaining_usd if sub else 0,
        "token_budget_count": int(float(sub.token_budget_usd or 0) * TOKENS_PER_USD) if sub else 0,
        "token_used_count": int(float(sub.token_used_usd or 0) * TOKENS_PER_USD) if sub else 0,
        "token_remaining_count": int(sub.token_remaining_usd * TOKENS_PER_USD) if sub else 0,
        "current_period_start": sub.current_period_start.isoformat() if sub and sub.current_period_start else None,
        "current_period_end": sub.current_period_end.isoformat() if sub and sub.current_period_end else None,
        "cancel_at_period_end": bool(sub.cancel_at_period_end) if sub else False,
        "cancelled_at": sub.cancelled_at.isoformat() if sub and sub.cancelled_at else None,
        "stripe_customer_id": user.stripe_customer_id,
    }


def activate_subscription(
    user: User,
    plan_id: str,
    *,
    stripe_subscription_id: str | None = None,
    stripe_price_id: str | None = None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    status: str = "active",
) -> UserSubscription:
    plan = get_plan(plan_id)
    if not plan:
        raise ValueError(f"Unknown plan: {plan_id}")

    sub = get_or_create_subscription(user)
    sub.plan_id = plan_id
    sub.status = status
    sub.stripe_subscription_id = stripe_subscription_id or sub.stripe_subscription_id
    sub.stripe_price_id = stripe_price_id or plan.stripe_price_id() or sub.stripe_price_id
    sub.token_budget_usd = plan.monthly_token_usd
    sub.token_used_usd = 0
    sub.current_period_start = period_start or _now()
    sub.current_period_end = period_end or (_now() + timedelta(days=30))
    sub.cancel_at_period_end = False
    sub.cancelled_at = None
    sub.updated_at = _now()

    user.subscription_status = status
    db.session.commit()

    log_event(user.id, "subscription_activated", plan_id=plan_id, token_delta_usd=plan.monthly_token_usd)
    return sub


def apply_plan_upgrade(user: User, new_plan_id: str) -> UserSubscription:
    plan = get_plan(new_plan_id)
    if not plan:
        raise ValueError(f"Unknown plan: {new_plan_id}")

    sub = get_or_create_subscription(user)
    old_plan_id = sub.plan_id or "starter"
    credit = upgrade_token_credit_usd(old_plan_id, new_plan_id)

    sub.plan_id = new_plan_id
    sub.stripe_price_id = plan.stripe_price_id() or sub.stripe_price_id
    if credit > 0:
        sub.token_budget_usd = float(sub.token_budget_usd or 0) + credit
    sub.status = "active"
    sub.updated_at = _now()
    user.subscription_status = "active"
    db.session.commit()

    log_event(
        user.id,
        "plan_upgraded",
        plan_id=new_plan_id,
        amount_usd=plan.price_usd,
        token_delta_usd=credit,
        payload={"from_plan": old_plan_id},
    )
    return sub


def renew_billing_period(user: User, plan_id: str | None = None) -> UserSubscription:
    """Reset token allowance at monthly refresh — no carryover."""
    sub = get_or_create_subscription(user)
    pid = plan_id or sub.plan_id or "starter"
    plan = get_plan(pid)
    if not plan:
        raise ValueError(f"Unknown plan: {pid}")

    sub.plan_id = pid
    sub.token_budget_usd = plan.monthly_token_usd
    sub.token_used_usd = 0
    sub.current_period_start = _now()
    sub.current_period_end = _now() + timedelta(days=30)
    sub.status = "active"
    sub.updated_at = _now()
    user.subscription_status = "active"
    db.session.commit()

    log_event(
        user.id,
        "period_renewed",
        plan_id=pid,
        token_delta_usd=plan.monthly_token_usd,
    )
    return sub


def mark_cancel_at_period_end(user: User) -> UserSubscription:
    sub = get_or_create_subscription(user)
    sub.cancel_at_period_end = True
    sub.updated_at = _now()
    db.session.commit()
    log_event(user.id, "cancel_scheduled", plan_id=sub.plan_id)
    return sub


def reset_subscription_to_free(user: User) -> UserSubscription:
    """Clear paid plan state — used when revoking dev-mode or manual activations."""
    sub = get_or_create_subscription(user)
    sub.plan_id = "starter"
    sub.status = "inactive"
    sub.stripe_subscription_id = None
    sub.stripe_price_id = None
    sub.token_budget_usd = 0
    sub.token_used_usd = 0
    sub.current_period_start = None
    sub.current_period_end = None
    sub.cancel_at_period_end = False
    sub.cancelled_at = None
    sub.updated_at = _now()
    user.subscription_status = "inactive"
    db.session.commit()
    log_event(user.id, "subscription_reset_free")
    return sub


def mark_subscription_cancelled(user: User) -> UserSubscription:
    sub = get_or_create_subscription(user)
    sub.status = "cancelled"
    sub.cancel_at_period_end = False
    sub.cancelled_at = _now()
    sub.updated_at = _now()
    user.subscription_status = "cancelled"
    db.session.commit()
    log_event(user.id, "subscription_cancelled", plan_id=sub.plan_id)
    return sub


def reactivate_subscription(user: User) -> UserSubscription:
    sub = get_or_create_subscription(user)
    sub.cancel_at_period_end = False
    sub.cancelled_at = None
    if sub.status == "cancelled":
        sub.status = "inactive"
    sub.updated_at = _now()
    db.session.commit()
    log_event(user.id, "cancel_revoked", plan_id=sub.plan_id)
    return sub


def record_token_usage(user: User, cost_usd: float) -> UserSubscription | None:
    if cost_usd <= 0:
        return get_subscription(user)
    sub = get_subscription(user)
    if not sub:
        return None
    sub.token_used_usd = float(sub.token_used_usd or 0) + cost_usd
    sub.updated_at = _now()
    db.session.commit()
    return sub


def ensure_token_budget(user: User, cost_usd: float) -> tuple[bool, str | None]:
    """Return (allowed, error_message)."""
    if current_app.config.get("DISABLE_AUTH"):
        return True, None
    sub = get_subscription(user)
    if not subscription_access_granted(sub):
        return False, "An active subscription is required."
    if sub.token_remaining_usd < cost_usd:
        return False, "Monthly API token allowance exhausted. Upgrade your plan or wait until renewal."
    return True, None
