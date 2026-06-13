"""LLM usage logging from Cursor run metadata."""

from backend.app import create_app
from backend.models import LlmUsageEvent, User, UserSubscription, db
from backend.services.billing_plans import actual_cost_to_billed_usd
from backend.services.llm_usage_context import LlmUsageContext, llm_usage_scope
from backend.services.llm_usage_service import record_cursor_run, tokens_to_cost_usd
from backend.services.subscription_service import activate_subscription, subscription_to_dict


def test_tokens_to_cost_usd_composer_fast_rates():
    usage = {
        "inputTokens": 1_000_000,
        "outputTokens": 0,
        "cacheReadTokens": 0,
        "cacheWriteTokens": 0,
        "totalTokens": 1_000_000,
    }
    assert tokens_to_cost_usd(usage) == 3.0

    usage["outputTokens"] = 1_000_000
    usage["totalTokens"] = 2_000_000
    assert tokens_to_cost_usd(usage) == 18.0


def test_actual_cost_to_billed_usd_forty_percent_margin():
    assert actual_cost_to_billed_usd(6.0) == 10.0


def test_record_cursor_run_applies_margin_to_subscription(monkeypatch):
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })

    def fake_fetch(agent_id, run_id):
        return {
            "inputTokens": 2_000_000,
            "outputTokens": 0,
            "cacheReadTokens": 0,
            "cacheWriteTokens": 0,
            "totalTokens": 2_000_000,
        }

    monkeypatch.setattr("backend.services.llm_usage_service.fetch_run_usage", fake_fetch)

    with app.app_context():
        user = User(email="llm-usage@test.com")
        user.set_password("securepass1")
        db.session.add(user)
        db.session.commit()

        activate_subscription(user, "starter")
        sub = UserSubscription.query.filter_by(user_id=user.id).first()
        assert float(sub.token_budget_usd) == 10.0
        assert float(sub.token_used_usd or 0) == 0

        ctx = LlmUsageContext(user_id=user.id, thread_id=None, source="chat")
        with llm_usage_scope(ctx):
            event = record_cursor_run("bc-agent-1", "run-abc-123")

        assert event is not None
        assert float(event.cost_usd) == 6.0
        assert float(event.billed_usd) == 10.0

        sub = UserSubscription.query.filter_by(user_id=user.id).first()
        assert float(sub.token_used_usd) == 10.0

        count = LlmUsageEvent.query.filter_by(user_id=user.id).count()
        assert count == 1


def test_subscription_at_token_limit_flag():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
        "STRIPE_SECRET_KEY": "",
    })
    with app.app_context():
        user = User(email="limit@test.com")
        user.set_password("securepass1")
        db.session.add(user)
        db.session.commit()

        activate_subscription(user, "starter")
        sub = UserSubscription.query.filter_by(user_id=user.id).first()
        sub.token_used_usd = sub.token_budget_usd
        db.session.commit()

        data = subscription_to_dict(sub, user)
        assert data["at_token_limit"] is True
        assert data["token_usage_percent"] == 100
