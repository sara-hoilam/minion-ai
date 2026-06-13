"""LLM usage logging from Cursor run metadata."""

from backend.app import create_app
from backend.models import LlmUsageEvent, User, UserSubscription, db
from backend.services.llm_usage_context import LlmUsageContext, llm_usage_scope
from backend.services.llm_usage_service import record_cursor_run, tokens_to_cost_usd
from backend.services.subscription_service import activate_subscription, subscription_to_dict


def test_tokens_to_cost_usd():
    usage = {
        "inputTokens": 1_000_000,
        "outputTokens": 0,
        "cacheReadTokens": 0,
        "cacheWriteTokens": 0,
        "totalTokens": 1_000_000,
    }
    assert tokens_to_cost_usd(usage) == 1.25

    usage["outputTokens"] = 1_000_000
    usage["totalTokens"] = 2_000_000
    assert tokens_to_cost_usd(usage) == 7.25


def test_record_cursor_run_persists_event_and_updates_subscription(monkeypatch):
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })

    def fake_fetch(agent_id, run_id):
        return {
            "inputTokens": 4000,
            "outputTokens": 1000,
            "cacheReadTokens": 2000,
            "cacheWriteTokens": 500,
            "totalTokens": 7500,
        }

    monkeypatch.setattr("backend.services.llm_usage_service.fetch_run_usage", fake_fetch)

    with app.app_context():
        user = User(email="llm-usage@test.com")
        user.set_password("securepass1")
        db.session.add(user)
        db.session.commit()

        activate_subscription(user, "starter")
        sub = UserSubscription.query.filter_by(user_id=user.id).first()
        assert float(sub.token_used_usd or 0) == 0

        ctx = LlmUsageContext(user_id=user.id, thread_id=None, source="chat")
        with llm_usage_scope(ctx):
            event = record_cursor_run("bc-agent-1", "run-abc-123")

        assert event is not None
        assert event.total_tokens == 7500
        assert event.user_id == user.id
        assert event.cursor_run_id == "run-abc-123"

        sub = UserSubscription.query.filter_by(user_id=user.id).first()
        assert float(sub.token_used_usd or 0) > 0

        count = LlmUsageEvent.query.filter_by(user_id=user.id).count()
        assert count == 1

        with llm_usage_scope(ctx):
            again = record_cursor_run("bc-agent-1", "run-abc-123")
        assert again.id == event.id
        assert LlmUsageEvent.query.filter_by(user_id=user.id).count() == 1


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
