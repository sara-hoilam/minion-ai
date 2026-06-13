"""Subscription plan math and access rules."""

from datetime import datetime, timedelta, timezone

from backend.app import create_app
from backend.models import User, UserSubscription, db
from backend.services.billing_plans import (
    PLANS,
    TOKEN_ALLOWANCE_RATIO,
    get_plan,
    upgrade_token_credit_usd,
)
from backend.services.subscription_service import (
    activate_subscription,
    apply_plan_upgrade,
    subscription_access_granted,
    subscription_to_dict,
)


def test_plan_monthly_token_allowance():
    assert TOKEN_ALLOWANCE_RATIO == 0.60
    assert get_plan("starter").monthly_token_usd == 6.0
    assert get_plan("growth").monthly_token_usd == 15.0
    assert get_plan("professional").monthly_token_usd == 36.0
    assert get_plan("business").monthly_token_usd == 90.0
    assert get_plan("starter").monthly_token_count == 600_000
    assert get_plan("growth").monthly_token_count == 1_500_000
    assert get_plan("professional").monthly_token_count == 3_600_000
    assert get_plan("business").monthly_token_count == 9_000_000


def test_upgrade_token_credit_is_sixty_percent_of_price_difference():
    assert upgrade_token_credit_usd("starter", "growth") == 9.0
    assert upgrade_token_credit_usd("growth", "professional") == 21.0
    assert upgrade_token_credit_usd("professional", "starter") == 0.0
    assert upgrade_token_credit_usd("unknown", "growth") == 0.0


def test_subscription_access_granted_active_within_period():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
        "STRIPE_SECRET_KEY": "",
    })
    with app.app_context():
        user = User(email="sub@test.com")
        user.set_password("securepass1")
        db.session.add(user)
        db.session.commit()

        now = datetime.now(timezone.utc)
        sub = UserSubscription(
            user_id=user.id,
            plan_id="starter",
            status="active",
            token_budget_usd=6.0,
            token_used_usd=1.0,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
        db.session.add(sub)
        db.session.commit()

        assert subscription_access_granted(sub) is True
        assert subscription_to_dict(sub, user)["access_granted"] is True


def test_subscription_access_denied_when_inactive_or_expired():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    with app.app_context():
        user = User(email="nosub@test.com")
        user.set_password("securepass1")
        db.session.add(user)
        db.session.commit()

        assert subscription_access_granted(None) is False

        inactive = UserSubscription(user_id=user.id, plan_id="starter", status="inactive")
        db.session.add(inactive)
        db.session.commit()
        assert subscription_access_granted(inactive) is False

        past = datetime.now(timezone.utc) - timedelta(days=1)
        inactive.status = "active"
        inactive.current_period_end = past
        inactive.cancel_at_period_end = False
        db.session.commit()
        assert subscription_access_granted(inactive) is False


def test_apply_plan_upgrade_adds_token_credit_not_full_reset():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    with app.app_context():
        user = User(email="upgrade@test.com")
        user.set_password("securepass1")
        db.session.add(user)
        db.session.commit()

        activate_subscription(user, "starter")
        sub = UserSubscription.query.filter_by(user_id=user.id).first()
        sub.token_used_usd = 2.0
        db.session.commit()

        apply_plan_upgrade(user, "growth")
        sub = UserSubscription.query.filter_by(user_id=user.id).first()
        assert sub.plan_id == "growth"
        assert float(sub.token_budget_usd) == 15.0  # 6 starter + 9 upgrade credit
        assert float(sub.token_used_usd) == 2.0


def test_subscription_access_denied_without_stripe_subscription_when_stripe_enabled():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
        "STRIPE_SECRET_KEY": "sk_test_fake",
        "STRIPE_PRICE_STARTER": "price_test_starter",
    })
    with app.app_context():
        user = User(email="stripeonly@test.com")
        user.set_password("securepass1")
        db.session.add(user)
        db.session.commit()

        now = datetime.now(timezone.utc)
        sub = UserSubscription(
            user_id=user.id,
            plan_id="professional",
            status="active",
            token_budget_usd=36.0,
            token_used_usd=0,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
        db.session.add(sub)
        db.session.commit()

        assert subscription_access_granted(sub) is False
        assert subscription_to_dict(sub, user)["access_granted"] is False


def test_post_message_returns_402_without_subscription():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
        "SUPABASE_ANON_KEY": "",
        "SUPABASE_URL": "",
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "blocked@test.com", "password": "securepass1"})
    client.post("/api/profile/background", json={
        "full_name": "Blocked",
        "field": "Finance",
        "skillset": "SQL",
        "current_job": "Analyst",
        "industry": "SaaS",
    })
    jd = {"title": "Analyst", "summary": "Finance agent.", "responsibilities": ["Analyze data"]}
    fw = client.post("/api/agents/framework-preview", json={
        "full_name": "Blocked",
        "field": "Finance",
        "skillset": "SQL",
        "current_job": "Analyst",
        "industry": "SaaS",
        "job_description": jd,
    }).get_json()
    assert fw and fw.get("framework"), fw
    session_id = client.post("/api/agents/create", json={
        "full_name": "Blocked",
        "field": "Finance",
        "skillset": "SQL",
        "current_job": "Analyst",
        "industry": "SaaS",
        "job_description": jd,
        "framework_design": {"framework": fw["framework"], "construction_answers": {}},
    }).get_json()["session_id"]
    thread = client.post("/api/chat/threads", json={"agent_session_id": session_id}).get_json()

    r = client.post(f"/api/chat/threads/{thread['id']}/messages", json={"content": "Hello"})
    assert r.status_code == 402
    assert "subscription" in r.get_json()["error"].lower()


def test_billing_config_lists_all_plans():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    data = client.get("/api/billing/config").get_json()
    plan_ids = [p["id"] for p in data["plans"]]
    assert plan_ids == list(PLANS.keys())
    assert data["tokens_per_usd"] == 100_000
    assert data["plans"][0]["monthly_token_count"] == 600_000
