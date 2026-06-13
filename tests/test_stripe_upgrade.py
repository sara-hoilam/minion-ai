"""Stripe upgrade checkout flow."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from backend.app import create_app
from backend.models import User, UserSubscription, db
from backend.services.subscription_service import activate_subscription


def _login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_upgrade_returns_checkout_url_when_stripe_enabled():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
        "STRIPE_SECRET_KEY": "sk_test_fake",
        "STRIPE_PRICE_STARTER": "price_starter",
        "STRIPE_PRICE_GROWTH": "price_growth",
    })
    client = app.test_client()

    with app.app_context():
        user = User(email="upgrade-flow@test.com")
        user.set_password("securepass1")
        db.session.add(user)
        db.session.commit()

        now = datetime.now(timezone.utc)
        sub = UserSubscription(
            user_id=user.id,
            plan_id="starter",
            status="active",
            stripe_subscription_id="sub_test_123",
            token_budget_usd=10.0,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
        db.session.add(sub)
        db.session.commit()

    assert _login(client, "upgrade-flow@test.com", "securepass1").status_code == 200

    with patch(
        "backend.routes.billing.create_upgrade_checkout_session",
        return_value="https://checkout.stripe.com/upgrade-test",
    ):
        res = client.post(
            "/api/billing/upgrade",
            json={
                "plan_id": "growth",
                "success_url": "https://app.example/#/plans/success",
                "cancel_url": "https://app.example/#/home",
            },
        )

    assert res.status_code == 200
    data = res.get_json()
    assert data["checkout_url"] == "https://checkout.stripe.com/upgrade-test"
    assert "subscription" not in data


def test_upgrade_dev_mode_only_when_stripe_disabled():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
        "STRIPE_SECRET_KEY": "",
    })
    client = app.test_client()

    with app.app_context():
        user = User(email="dev-upgrade@test.com")
        user.set_password("securepass1")
        db.session.add(user)
        db.session.commit()
        activate_subscription(user, "starter")

    assert _login(client, "dev-upgrade@test.com", "securepass1").status_code == 200

    res = client.post("/api/billing/upgrade", json={"plan_id": "growth"})
    assert res.status_code == 200
    data = res.get_json()
    assert data.get("dev_mode") is True
    assert data["subscription"]["plan_id"] == "growth"
    assert "checkout_url" not in data
