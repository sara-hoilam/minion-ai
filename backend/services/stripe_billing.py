"""Stripe checkout, upgrades, webhooks."""

from __future__ import annotations

from datetime import datetime, timezone

import stripe

from backend.models import User, db
from backend.services.billing_plans import PLANS, get_plan, stripe_enabled
from backend.services.subscription_service import (
    activate_subscription,
    apply_plan_upgrade,
    log_event,
    mark_cancel_at_period_end,
    mark_subscription_cancelled,
    renew_billing_period,
    reactivate_subscription,
)


def _stripe():
    from flask import current_app

    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
    return stripe


def ensure_stripe_customer(user: User) -> str:
    if user.stripe_customer_id:
        return user.stripe_customer_id
    customer = _stripe().Customer.create(email=user.email, metadata={"user_id": str(user.id)})
    user.stripe_customer_id = customer.id
    db.session.commit()
    return customer.id


def create_checkout_session(user: User, plan_id: str, success_url: str, cancel_url: str) -> str:
    plan = get_plan(plan_id)
    if not plan:
        raise ValueError("Invalid plan")
    price_id = plan.stripe_price_id()
    if not price_id:
        raise ValueError(f"Stripe price not configured for plan {plan_id}")

    customer_id = ensure_stripe_customer(user)
    session = _stripe().checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"user_id": str(user.id), "plan_id": plan_id},
        subscription_data={"metadata": {"user_id": str(user.id), "plan_id": plan_id}},
    )
    log_event(user.id, "checkout_started", plan_id=plan_id, payload={"session_id": session.id})
    return session.url


def upgrade_subscription(user: User, new_plan_id: str) -> dict:
    """Upgrade plan — Stripe prorates charge; tokens credited at 60% of price difference."""
    from backend.models import UserSubscription

    plan = get_plan(new_plan_id)
    if not plan:
        raise ValueError("Invalid plan")
    price_id = plan.stripe_price_id()
    if not price_id:
        raise ValueError(f"Stripe price not configured for plan {new_plan_id}")

    sub = UserSubscription.query.filter_by(user_id=user.id).first()
    if not sub or not sub.stripe_subscription_id:
        raise ValueError("No active Stripe subscription to upgrade")

    stripe_sub = _stripe().Subscription.retrieve(sub.stripe_subscription_id)
    item_id = stripe_sub["items"]["data"][0]["id"]
    _stripe().Subscription.modify(
        sub.stripe_subscription_id,
        items=[{"id": item_id, "price": price_id}],
        proration_behavior="always_invoice",
        metadata={"user_id": str(user.id), "plan_id": new_plan_id},
    )

    updated = apply_plan_upgrade(user, new_plan_id)
    sub.stripe_price_id = price_id
    db.session.commit()
    return {"plan_id": updated.plan_id, "token_budget_usd": float(updated.token_budget_usd)}


def schedule_cancel(user: User) -> None:
    from backend.models import UserSubscription

    sub = UserSubscription.query.filter_by(user_id=user.id).first()
    if sub and sub.stripe_subscription_id:
        _stripe().Subscription.modify(sub.stripe_subscription_id, cancel_at_period_end=True)
    mark_cancel_at_period_end(user)


def revoke_cancel(user: User) -> None:
    from backend.models import UserSubscription

    sub = UserSubscription.query.filter_by(user_id=user.id).first()
    if sub and sub.stripe_subscription_id:
        _stripe().Subscription.modify(sub.stripe_subscription_id, cancel_at_period_end=False)
    reactivate_subscription(user)


def _plan_id_from_stripe_price(price_id: str | None) -> str | None:
    if not price_id:
        return None
    for plan in PLANS.values():
        if plan.stripe_price_id() == price_id:
            return plan.id
    return None


def _ts_to_dt(ts: int | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def handle_webhook_event(event: dict) -> None:
    etype = event.get("type", "")
    data = event.get("data", {}).get("object", {})
    event_id = event.get("id")

    if etype == "checkout.session.completed":
        _handle_checkout_completed(data, event_id)
    elif etype == "invoice.paid":
        _handle_invoice_paid(data, event_id)
    elif etype == "customer.subscription.updated":
        _handle_subscription_updated(data, event_id)
    elif etype == "customer.subscription.deleted":
        _handle_subscription_deleted(data, event_id)


def _user_from_metadata(meta: dict) -> User | None:
    uid = meta.get("user_id")
    if not uid:
        return None
    return db.session.get(User, int(uid))


def _handle_checkout_completed(session: dict, event_id: str | None) -> None:
    if session.get("mode") != "subscription":
        return
    user = _user_from_metadata(session.get("metadata") or {})
    if not user:
        return
    plan_id = (session.get("metadata") or {}).get("plan_id") or "starter"
    sub_id = session.get("subscription")
    stripe_sub = _stripe().Subscription.retrieve(sub_id) if sub_id else None
    price_id = None
    period_start = period_end = None
    if stripe_sub:
        price_id = stripe_sub["items"]["data"][0]["price"]["id"]
        plan_id = _plan_id_from_stripe_price(price_id) or plan_id
        period_start = _ts_to_dt(stripe_sub.get("current_period_start"))
        period_end = _ts_to_dt(stripe_sub.get("current_period_end"))

    activate_subscription(
        user,
        plan_id,
        stripe_subscription_id=sub_id,
        stripe_price_id=price_id,
        period_start=period_start,
        period_end=period_end,
    )
    log_event(user.id, "checkout_completed", plan_id=plan_id, stripe_event_id=event_id)


def _handle_invoice_paid(invoice: dict, event_id: str | None) -> None:
    if invoice.get("billing_reason") not in ("subscription_cycle", "subscription_create"):
        return
    sub_id = invoice.get("subscription")
    if not sub_id:
        return
    stripe_sub = _stripe().Subscription.retrieve(sub_id)
    meta = stripe_sub.get("metadata") or {}
    user = _user_from_metadata(meta)
    if not user:
        customer_id = invoice.get("customer")
        user = User.query.filter_by(stripe_customer_id=customer_id).first()
    if not user:
        return

    price_id = stripe_sub["items"]["data"][0]["price"]["id"]
    plan_id = _plan_id_from_stripe_price(price_id) or meta.get("plan_id") or "starter"

    if invoice.get("billing_reason") == "subscription_create":
        activate_subscription(
            user,
            plan_id,
            stripe_subscription_id=sub_id,
            stripe_price_id=price_id,
            period_start=_ts_to_dt(stripe_sub.get("current_period_start")),
            period_end=_ts_to_dt(stripe_sub.get("current_period_end")),
        )
    else:
        sub = renew_billing_period(user, plan_id)
        sub.stripe_subscription_id = sub_id
        sub.stripe_price_id = price_id
        sub.current_period_start = _ts_to_dt(stripe_sub.get("current_period_start"))
        sub.current_period_end = _ts_to_dt(stripe_sub.get("current_period_end"))
        db.session.commit()

    log_event(
        user.id,
        "invoice_paid",
        plan_id=plan_id,
        amount_usd=(invoice.get("amount_paid") or 0) / 100.0,
        stripe_event_id=event_id,
    )


def _handle_subscription_updated(stripe_sub: dict, event_id: str | None) -> None:
    sub_id = stripe_sub.get("id")
    from backend.models import UserSubscription

    row = UserSubscription.query.filter_by(stripe_subscription_id=sub_id).first()
    user = row.user if row else None
    if not user:
        user = _user_from_metadata(stripe_sub.get("metadata") or {})
    if not user:
        customer_id = stripe_sub.get("customer")
        user = User.query.filter_by(stripe_customer_id=customer_id).first()
    if not user:
        return

    from backend.services.subscription_service import get_or_create_subscription

    sub = row or get_or_create_subscription(user)
    price_id = stripe_sub["items"]["data"][0]["price"]["id"]
    plan_id = _plan_id_from_stripe_price(price_id) or sub.plan_id
    sub.plan_id = plan_id
    sub.stripe_price_id = price_id
    sub.stripe_subscription_id = sub_id
    sub.status = stripe_sub.get("status") or sub.status
    sub.cancel_at_period_end = bool(stripe_sub.get("cancel_at_period_end"))
    sub.current_period_start = _ts_to_dt(stripe_sub.get("current_period_start"))
    sub.current_period_end = _ts_to_dt(stripe_sub.get("current_period_end"))
    user.subscription_status = sub.status
    db.session.commit()
    log_event(user.id, "subscription_updated", plan_id=plan_id, stripe_event_id=event_id)


def _handle_subscription_deleted(stripe_sub: dict, event_id: str | None) -> None:
    from backend.models import UserSubscription

    sub_id = stripe_sub.get("id")
    row = UserSubscription.query.filter_by(stripe_subscription_id=sub_id).first()
    if not row:
        return
    mark_subscription_cancelled(row.user)
    log_event(row.user_id, "subscription_deleted", stripe_event_id=event_id)
