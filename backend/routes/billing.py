from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from backend.models import db
from backend.services.billing_plans import PLAN_ORDER, PLANS, TOKENS_PER_USD, stripe_enabled
from backend.services.event_logger import log_event
from backend.services.stripe_billing import (
    create_checkout_session,
    handle_webhook_event,
    revoke_cancel,
    schedule_cancel,
    upgrade_subscription,
)
from backend.services.subscription_service import (
    activate_subscription,
    get_or_create_subscription,
    get_subscription,
    subscription_to_dict,
)

billing_bp = Blueprint("billing", __name__, url_prefix="/api/billing")


@billing_bp.route("/config", methods=["GET"])
def billing_config():
    return jsonify({
        "publishable_key": current_app.config.get("STRIPE_PUBLISHABLE_KEY", ""),
        "stripe_enabled": stripe_enabled(),
        "tokens_per_usd": TOKENS_PER_USD,
        "plans": [PLANS[pid].to_dict() for pid in PLAN_ORDER],
    })


@billing_bp.route("/plans", methods=["GET"])
def list_plans():
    return jsonify({"plans": [PLANS[pid].to_dict() for pid in PLAN_ORDER]})


@billing_bp.route("/subscription", methods=["GET"])
@login_required
def get_user_subscription():
    sub = get_subscription(current_user)
    return jsonify(subscription_to_dict(sub, current_user))


@billing_bp.route("/checkout", methods=["POST"])
@login_required
def create_checkout():
    data = request.get_json() or {}
    plan_id = (data.get("plan_id") or "starter").strip()
    if plan_id not in PLANS:
        return jsonify({"error": "Invalid plan"}), 400

    success_url = data.get("success_url") or f"{current_app.config.get('APP_URL', 'http://localhost:5000')}/#/plans/success"
    cancel_url = data.get("cancel_url") or f"{current_app.config.get('APP_URL', 'http://localhost:5000')}/#/plans"

    if not stripe_enabled():
        activate_subscription(current_user, plan_id)
        log_event("subscription_activated_dev_mode", {"plan_id": plan_id, "user_id": current_user.id})
        return jsonify({
            "ok": True,
            "dev_mode": True,
            "message": f"{PLANS[plan_id].name} plan activated (Stripe not configured).",
            "subscription": subscription_to_dict(get_subscription(current_user), current_user),
        })

    try:
        url = create_checkout_session(current_user, plan_id, success_url, cancel_url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"checkout_url": url})


@billing_bp.route("/upgrade", methods=["POST"])
@login_required
def upgrade_plan():
    data = request.get_json() or {}
    plan_id = (data.get("plan_id") or "").strip()
    if plan_id not in PLANS:
        return jsonify({"error": "Invalid plan"}), 400

    sub = get_subscription(current_user)
    if not sub or not sub.plan_id:
        return jsonify({"error": "Subscribe to a plan first"}), 400

    current_plan = PLANS[sub.plan_id]
    new_plan = PLANS[plan_id]
    if new_plan.price_usd <= current_plan.price_usd:
        return jsonify({"error": "Choose a higher plan to upgrade"}), 400

    if not stripe_enabled() or not sub.stripe_subscription_id:
        from backend.services.subscription_service import apply_plan_upgrade

        apply_plan_upgrade(current_user, plan_id)
        return jsonify({
            "ok": True,
            "dev_mode": True,
            "subscription": subscription_to_dict(get_subscription(current_user), current_user),
        })

    try:
        result = upgrade_subscription(current_user, plan_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({
        "ok": True,
        "subscription": subscription_to_dict(get_subscription(current_user), current_user),
        **result,
    })


@billing_bp.route("/cancel", methods=["POST"])
@login_required
def cancel_subscription():
    sub = get_subscription(current_user)
    if not sub or sub.status not in ("active", "trialing"):
        return jsonify({"error": "No active subscription to cancel"}), 400

    if stripe_enabled() and sub.stripe_subscription_id:
        try:
            schedule_cancel(current_user)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400
    else:
        from backend.services.subscription_service import mark_cancel_at_period_end

        mark_cancel_at_period_end(current_user)

    return jsonify({
        "ok": True,
        "subscription": subscription_to_dict(get_subscription(current_user), current_user),
        "message": "Subscription will cancel at the end of the billing period.",
    })


@billing_bp.route("/reactivate", methods=["POST"])
@login_required
def reactivate():
    sub = get_subscription(current_user)
    if not sub or not sub.cancel_at_period_end:
        return jsonify({"error": "Nothing to reactivate"}), 400

    if stripe_enabled() and sub.stripe_subscription_id:
        try:
            revoke_cancel(current_user)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400
    else:
        from backend.services.subscription_service import reactivate_subscription

        reactivate_subscription(current_user)

    return jsonify({
        "ok": True,
        "subscription": subscription_to_dict(get_subscription(current_user), current_user),
    })


@billing_bp.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")
    secret = current_app.config.get("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        return jsonify({"error": "Webhook secret not configured"}), 503

    import stripe

    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
    try:
        event = stripe.Webhook.construct_event(payload, sig, secret)
    except ValueError:
        return jsonify({"error": "Invalid payload"}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({"error": "Invalid signature"}), 400

    handle_webhook_event(event)
    db.session.commit()
    return jsonify({"received": True})


# Legacy status endpoint
@billing_bp.route("/status", methods=["GET"])
@login_required
def subscription_status():
    sub = get_subscription(current_user)
    data = subscription_to_dict(sub, current_user)
    data["status_legacy"] = current_user.subscription_status
    return jsonify(data)
