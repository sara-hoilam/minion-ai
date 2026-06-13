"""Stripe checkout, upgrades, webhooks."""

from __future__ import annotations

from datetime import datetime, timezone

import stripe

from backend.models import User, db
from backend.services.billing_plans import PLANS, get_plan
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


def create_upgrade_checkout_session(
    user: User,
    new_plan_id: str,
    success_url: str,
    cancel_url: str,
) -> str:
    """Send the user to Stripe to confirm and pay for a plan upgrade."""
    from backend.models import UserSubscription

    plan = get_plan(new_plan_id)
    if not plan:
        raise ValueError("Invalid plan")
    price_id = plan.stripe_price_id()
    if not price_id:
        raise ValueError(f"Stripe price not configured for plan {new_plan_id}")

    sub = UserSubscription.query.filter_by(user_id=user.id).first()
    if not sub or not sub.stripe_subscription_id:
        return create_checkout_session(user, new_plan_id, success_url, cancel_url)

    customer_id = ensure_stripe_customer(user)
    stripe_sub = _stripe().Subscription.retrieve(sub.stripe_subscription_id)
    item_id = stripe_sub["items"]["data"][0]["id"]
    current_price_id = stripe_sub["items"]["data"][0]["price"]["id"]
    if current_price_id == price_id:
        raise ValueError("Already on this plan")

    # Billing Portal shows a Stripe-hosted confirmation + payment step.
    try:
        portal = _stripe().billing_portal.Session.create(
            customer=customer_id,
            return_url=success_url,
            flow_data={
                "type": "subscription_update_confirm",
                "subscription_update_confirm": {
                    "subscription": sub.stripe_subscription_id,
                    "items": [{"id": item_id, "price": price_id, "quantity": 1}],
                },
                "after_completion": {
                    "type": "redirect",
                    "redirect": {"return_url": success_url},
                },
            },
        )
        log_event(
            user.id,
            "upgrade_checkout_started",
            plan_id=new_plan_id,
            payload={"session_id": portal.id, "via": "portal"},
        )
        return portal.url
    except stripe.error.StripeError:
        pass

    # Fallback: open the proration invoice on Stripe's hosted invoice page.
    updated = _stripe().Subscription.modify(
        sub.stripe_subscription_id,
        items=[{"id": item_id, "price": price_id}],
        proration_behavior="always_invoice",
        payment_behavior="pending_if_incomplete",
        expand=["latest_invoice"],
    )
    invoice = updated["latest_invoice"]
    if isinstance(invoice, str):
        invoice = _stripe().Invoice.retrieve(invoice)

    hosted = invoice.get("hosted_invoice_url")
    if hosted and invoice.get("status") not in ("paid", "void"):
        log_event(
            user.id,
            "upgrade_checkout_started",
            plan_id=new_plan_id,
            payload={"invoice_id": invoice.get("id"), "via": "invoice"},
        )
        return hosted

    if invoice.get("status") == "paid":
        apply_plan_upgrade(user, new_plan_id)
        sub.stripe_price_id = price_id
        db.session.commit()
        sep = "&" if "?" in success_url else "?"
        return f"{success_url}{sep}upgraded=1"

    raise ValueError(
        "Unable to start upgrade payment. Check your Stripe Customer Portal settings "
        "or add a payment method, then try again."
    )


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
    billing_reason = invoice.get("billing_reason")
    if billing_reason not in ("subscription_cycle", "subscription_create", "subscription_update"):
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

    if billing_reason == "subscription_create":
        activate_subscription(
            user,
            plan_id,
            stripe_subscription_id=sub_id,
            stripe_price_id=price_id,
            period_start=_ts_to_dt(stripe_sub.get("current_period_start")),
            period_end=_ts_to_dt(stripe_sub.get("current_period_end")),
        )
    elif billing_reason == "subscription_update":
        from backend.models import UserSubscription

        sub = UserSubscription.query.filter_by(user_id=user.id).first()
        if sub:
            _sync_subscription_from_stripe(
                user, sub, stripe_sub, price_id, plan_id, apply_upgrade_credit=True
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


def _sync_subscription_from_stripe(
    user: User,
    sub,
    stripe_sub: dict,
    price_id: str,
    plan_id: str,
    *,
    apply_upgrade_credit: bool = False,
) -> None:
    """Apply local subscription state after Stripe confirms a plan change."""
    from backend.models import UserSubscription

    old_plan_id = sub.plan_id
    old_plan = get_plan(old_plan_id) if old_plan_id else None
    new_plan = get_plan(plan_id)
    is_upgrade = (
        old_plan
        and new_plan
        and new_plan.price_usd > old_plan.price_usd
        and old_plan_id != plan_id
    )

    if is_upgrade and apply_upgrade_credit:
        apply_plan_upgrade(user, plan_id)
        sub = UserSubscription.query.filter_by(user_id=user.id).first()
    else:
        sub.plan_id = plan_id

    sub.stripe_price_id = price_id
    sub.stripe_subscription_id = stripe_sub.get("id") or sub.stripe_subscription_id
    sub.status = stripe_sub.get("status") or sub.status
    sub.cancel_at_period_end = bool(stripe_sub.get("cancel_at_period_end"))
    sub.current_period_start = _ts_to_dt(stripe_sub.get("current_period_start"))
    sub.current_period_end = _ts_to_dt(stripe_sub.get("current_period_end"))
    user.subscription_status = sub.status
    db.session.commit()


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
    _sync_subscription_from_stripe(
        user, sub, stripe_sub, price_id, plan_id, apply_upgrade_credit=False
    )
    log_event(user.id, "subscription_updated", plan_id=plan_id, stripe_event_id=event_id)


def _handle_subscription_deleted(stripe_sub: dict, event_id: str | None) -> None:
    from backend.models import UserSubscription

    sub_id = stripe_sub.get("id")
    row = UserSubscription.query.filter_by(stripe_subscription_id=sub_id).first()
    if not row:
        return
    mark_subscription_cancelled(row.user)
    log_event(row.user_id, "subscription_deleted", stripe_event_id=event_id)
