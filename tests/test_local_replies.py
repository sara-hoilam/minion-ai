"""Instant local replies — no Cursor API."""

from backend.services.local_replies import normalize_user_query, try_instant_reply
from backend.services.thinking_principles import today_label


def test_normalize_strips_agent_mention():
    assert normalize_user_query("@Richard Hi Richard, what date is it today?") == (
        "Hi Richard, what date is it today?"
    )


def test_instant_date_reply():
    reply = try_instant_reply("@Richard what date is it today?", "Richard")
    assert reply is not None
    assert today_label() in reply


def test_instant_greeting():
    reply = try_instant_reply("Hello", "Aria")
    assert reply is not None
    assert "Aria" in reply
