"""Subscription plan math and access rules."""

from datetime import datetime, timedelta, timezone

from backend.app import create_app
from backend.models import User, UserSubscription, db
from backend.services.billing_plans import (
    PLANS,
    TOKEN_ALLOWANCE_RATIO,
    actual_cost_to_billed_usd,
    get_plan,
    upgrade_token_credit_usd,
)
from backend.services.subscription_service import (
    activate_subscription,
    apply_plan_upgrade,
    subscription_access_granted,
    subscription_to_dict,
)


def test_all_plans_apply_billed_budget_and_api_cap():
    expected = {
        "starter": (10.0, 6.0, 1_000_000),
        "growth": (25.0, 15.0, 2_500_000),
        "professional": (60.0, 36.0, 6_000_000),
        "business": (150.0, 90.0, 15_000_000),
    }
    for plan_id, (billed, api_cap, tokens) in expected.items():
        plan = get_plan(plan_id)
        assert plan.monthly_billed_usd == billed
        assert plan.monthly_api_usd == api_cap
        assert plan.monthly_token_count == tokens


def test_activate_subscription_sets_billed_budget_for_each_plan():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    with app.app_context():
        for plan_id, (billed, _, _) in {
            "starter": (10.0, 6.0, 1_000_000),
            "growth": (25.0, 15.0, 2_500_000),
            "professional": (60.0, 36.0, 6_000_000),
            "business": (150.0, 90.0, 15_000_000),
        }.items():
            user = User(email=f"{plan_id}@test.com")
            user.set_password("securepass1")
            db.session.add(user)
            db.session.commit()
            activate_subscription(user, plan_id)
            sub = UserSubscription.query.filter_by(user_id=user.id).first()
            assert float(sub.token_budget_usd) == billed, plan_id
            db.session.delete(sub)
            db.session.delete(user)
            db.session.commit()


def test_plan_monthly_token_allowance():
    assert TOKEN_ALLOWANCE_RATIO == 0.60
    starter = get_plan("starter")
    assert starter.monthly_billed_usd == 10.0
    assert starter.monthly_api_usd == 6.0
    assert starter.monthly_token_usd == 10.0
    assert get_plan("growth").monthly_billed_usd == 25.0
    assert get_plan("growth").monthly_api_usd == 15.0
    assert get_plan("professional").monthly_api_usd == 36.0
    assert get_plan("business").monthly_api_usd == 90.0
    assert starter.monthly_token_count == 1_000_000
    assert get_plan("growth").monthly_token_count == 2_500_000
    assert get_plan("professional").monthly_token_count == 6_000_000
    assert get_plan("business").monthly_token_count == 15_000_000


def test_actual_cost_to_billed_applies_forty_percent_margin():
    assert actual_cost_to_billed_usd(6.0) == 10.0
    assert actual_cost_to_billed_usd(15.0) == 25.0


def test_upgrade_token_credit_is_full_price_difference():
    assert upgrade_token_credit_usd("starter", "growth") == 15.0
    assert upgrade_token_credit_usd("growth", "professional") == 35.0
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
            token_budget_usd=10.0,
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
        assert float(sub.token_budget_usd) == 25.0  # 10 starter + 15 upgrade credit
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
            token_budget_usd=60.0,
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
    client.post("/api/auth/register", json={"email": "blocked@test.com", "password": "securepass1", "first_name": "Test", "last_name": "User"})
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
    assert data["plans"][0]["monthly_token_count"] == 1_000_000
