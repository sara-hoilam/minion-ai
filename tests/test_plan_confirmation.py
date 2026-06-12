"""Workflow plan confirmation when delegation exceeds half the team."""

from backend.app import create_app
from backend.models import ChatThread, db
from backend.services.chat_orchestrator import plan_requires_confirmation, run_agent_turn
from tests.test_chat_orchestrator import PLAN_CONFIRMATION_PROMPT, _four_skill_framework


def _framework_and_context():
    framework = _four_skill_framework()
    context = {
        "full_name": "Sara",
        "field": "Finance",
        "industry": "SaaS",
        "current_job": "Financial Analyst",
        "skillset": "SQL, FP&A, forecasting, Tableau",
    }
    return framework, context


def test_plan_requires_confirmation_threshold():
    agents = [{"skill": f"S{i}"} for i in range(4)]
    assert plan_requires_confirmation([{}, {}, {}], agents)
    assert not plan_requires_confirmation([{}, {}], agents)
    assert not plan_requires_confirmation([], agents)


def test_large_team_plan_returns_confirmation(monkeypatch):
    monkeypatch.setattr("backend.services.chat_orchestrator.cursor_complete", lambda *a, **k: None)
    framework, context = _framework_and_context()
    result = run_agent_turn(
        context,
        framework,
        PLAN_CONFIRMATION_PROMPT,
    )
    assert result.get("needs_confirmation") is True
    assert result["meta"]["type"] == "plan_proposal"
    assert result["meta"]["delegated_count"] > result["meta"]["skill_count"] / 2


def _create_agent(client, name="Sara"):
    client.post("/api/profile/background", json={
        "full_name": name,
        "field": "Finance",
        "skillset": "FP&A, SQL, forecasting",
        "current_job": "Financial Analyst",
        "industry": "SaaS",
    })
    jd = {
        "title": f"Analyst — {name}",
        "summary": "Finance agent.",
        "responsibilities": ["Build forecasts", "Analyze funnel data", "Prepare reports"],
    }
    framework = _four_skill_framework()
    return client.post("/api/agents/create", json={
        "full_name": name,
        "field": "Finance",
        "skillset": "FP&A, SQL, forecasting",
        "current_job": "Financial Analyst",
        "industry": "SaaS",
        "job_description": jd,
        "framework_design": {"framework": framework, "construction_answers": {}},
    }).get_json()["session_id"]


def test_team_message_proposes_plan_before_execution():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "plan@test.com", "password": "securepass1"})
    session_id = _create_agent(client)
    thread = client.post("/api/chat/threads", json={"agent_session_id": session_id}).get_json()

    r = client.post(f"/api/chat/threads/{thread['id']}/messages", json={
        "content": PLAN_CONFIRMATION_PROMPT,
    })
    assert r.status_code == 202

    loaded = client.get(f"/api/chat/threads/{thread['id']}").get_json()
    assert loaded.get("pending_plan")
    assert loaded["is_generating"] is False
    assistant_msgs = [
        m for m in loaded["messages"]
        if m["role"] == "assistant" and (m.get("meta") or {}).get("type") != "welcome"
    ]
    assert assistant_msgs[-1]["meta"]["type"] == "plan_proposal"


def test_confirm_plan_marks_proposal_confirmed():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "confirmed@test.com", "password": "securepass1"})
    session_id = _create_agent(client)
    thread = client.post("/api/chat/threads", json={"agent_session_id": session_id}).get_json()

    client.post(f"/api/chat/threads/{thread['id']}/messages", json={
        "content": PLAN_CONFIRMATION_PROMPT,
    })

    client.post(f"/api/chat/threads/{thread['id']}/plan/confirm")

    loaded = client.get(f"/api/chat/threads/{thread['id']}").get_json()
    proposal = next(
        m for m in loaded["messages"]
        if m["role"] == "assistant" and (m.get("meta") or {}).get("type") == "plan_proposal"
    )
    assert proposal["meta"].get("confirmed") is True
    assert proposal["meta"]["progress_card"]["summary"] == "Confirmed to run"


def test_confirm_plan_starts_execution():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "confirm@test.com", "password": "securepass1"})
    session_id = _create_agent(client)
    thread = client.post("/api/chat/threads", json={"agent_session_id": session_id}).get_json()

    client.post(f"/api/chat/threads/{thread['id']}/messages", json={
        "content": PLAN_CONFIRMATION_PROMPT,
    })

    r = client.post(f"/api/chat/threads/{thread['id']}/plan/confirm")
    assert r.status_code == 202
    assert r.get_json().get("executing") is True

    loaded = client.get(f"/api/chat/threads/{thread['id']}").get_json()
    assert loaded.get("pending_plan") is None
