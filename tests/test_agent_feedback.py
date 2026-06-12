"""Agent feedback — filter pipeline and adaptation."""

from backend.app import create_app
from backend.models import AgentFeedback, StudioSession, db
from backend.services.feedback_filter import classify_feedback, feedback_status_from_classification


def _create_agent(client, name="Riley"):
    client.post("/api/profile/background", json={
        "full_name": name,
        "field": "Finance",
        "skillset": "FP&A, reporting",
        "current_job": "Analyst",
        "industry": "SaaS",
    })
    jd = {
        "title": f"Analyst — {name}",
        "summary": "Finance agent.",
        "responsibilities": ["Build forecasts"],
    }
    fw = client.post("/api/agents/framework-preview", json={
        "full_name": name,
        "field": "Finance",
        "skillset": "FP&A, reporting",
        "current_job": "Analyst",
        "industry": "SaaS",
        "job_description": jd,
    }).get_json()
    return client.post("/api/agents/create", json={
        "full_name": name,
        "field": "Finance",
        "skillset": "FP&A, reporting",
        "current_job": "Analyst",
        "industry": "SaaS",
        "job_description": jd,
        "framework_design": {"framework": fw["framework"], "construction_answers": {}},
    }).get_json()["session_id"]


def test_rule_based_filter_rejects_short_feedback():
    result = classify_feedback("ok", {"full_name": "Agent", "skillset": "analysis"})
    assert feedback_status_from_classification(result) == "filtered_out"


def test_rule_based_filter_accepts_constructive_feedback():
    text = "Please be more concise in your summaries and focus on key metrics only."
    result = classify_feedback(text, {
        "full_name": "Agent",
        "skillset": "data analysis",
        "current_job": "Analyst",
    })
    assert feedback_status_from_classification(result) == "approved"


def test_submit_dm_agent_feedback_api():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
        "TESTING": True,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "dmfb@test.com", "password": "securepass1"})
    session_id = _create_agent(client)

    res = client.post(
        f"/api/agents/{session_id}/feedback",
        json={"content": "Please improve accuracy in estimates and avoid false precision in summaries."},
    )
    assert res.status_code == 201
    body = res.get_json()
    assert body["status"] in ("approved", "filtered_out")

    with app.app_context():
        session = db.session.get(StudioSession, session_id)
        if body["status"] == "approved":
            assert session.agent_context.get("feedback_digest")


def test_submit_feedback_api():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
        "TESTING": True,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "feedback@test.com", "password": "securepass1"})
    session_id = _create_agent(client)

    project = client.post("/api/projects", json={
        "name": "Feedback project",
        "agent_session_ids": [session_id],
    }).get_json()

    res = client.post(
        f"/api/projects/{project['id']}/agents/{session_id}/feedback",
        json={"content": "Please improve accuracy in numerical estimates and cite sources."},
    )
    assert res.status_code == 201
    body = res.get_json()
    assert body["status"] == "approved"

    with app.app_context():
        entry = AgentFeedback.query.filter_by(project_id=project["id"]).first()
        assert entry is not None
        assert entry.applied_at is not None
        session = db.session.get(StudioSession, session_id)
        assert session.agent_context.get("feedback_digest")

    res2 = client.post(
        f"/api/projects/{project['id']}/agents/{session_id}/feedback",
        json={"content": "hi"},
    )
    assert res2.status_code == 400
