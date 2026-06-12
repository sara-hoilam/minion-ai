"""Agent rename, update, and delete."""

from pathlib import Path

from backend.app import create_app
from backend.config import AGENT_OUTPUT_FOLDER


def _create_agent(client):
    client.post("/api/profile/background", json={
        "full_name": "Original Bot",
        "field": "Finance",
        "skillset": "FP&A",
        "current_job": "Analyst",
        "industry": "Healthcare",
    })
    jd = {
        "title": "Analyst — Original Bot",
        "summary": "Finance agent.",
        "responsibilities": ["Build forecasts"],
    }
    fw = client.post("/api/agents/framework-preview", json={
        "full_name": "Original Bot",
        "field": "Finance",
        "skillset": "FP&A",
        "current_job": "Analyst",
        "industry": "Healthcare",
        "job_description": jd,
    }).get_json()

    return client.post("/api/agents/create", json={
        "full_name": "Original Bot",
        "field": "Finance",
        "skillset": "FP&A",
        "current_job": "Analyst",
        "industry": "Healthcare",
        "job_description": jd,
        "framework_design": {
            "framework": fw["framework"],
            "construction_answers": {},
        },
    }).get_json()["session_id"]


def test_rename_agent():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "rename@test.com", "password": "securepass1"})
    session_id = _create_agent(client)

    r = client.put(f"/api/agents/{session_id}", json={"full_name": "Sara"})
    assert r.status_code == 200

    home = client.get("/api/home").get_json()
    assert home["personas"][0]["name"] == "Sara"

    user_dir = Path(AGENT_OUTPUT_FOLDER) / "1"
    assert (user_dir / "sara_agent_framework.json").exists()
    assert (user_dir / "sara_skill.md").exists()


def test_get_agent():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "get@test.com", "password": "securepass1"})
    session_id = _create_agent(client)

    r = client.get(f"/api/agents/{session_id}")
    assert r.status_code == 200
    data = r.get_json()
    assert data["agent_name"] == "Original Bot"
    assert data["job_description"]["responsibilities"]


def test_delete_agent():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "del@test.com", "password": "securepass1"})
    session_id = _create_agent(client)

    r = client.delete(f"/api/agents/{session_id}")
    assert r.status_code == 200

    home = client.get("/api/home").get_json()
    assert len(home["personas"]) == 0

    assert client.get(f"/api/agents/{session_id}").status_code == 404


def test_hide_agent_from_roster():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "hide@test.com", "password": "securepass1"})
    session_id = _create_agent(client)
    client.post("/api/chat/threads", json={"agent_session_id": session_id})

    r = client.post(f"/api/agents/{session_id}/hide-from-roster")
    assert r.status_code == 200
    assert r.get_json()["hidden_from_roster"] is True

    home = client.get("/api/home").get_json()
    assert len(home["personas"]) == 0

    sidebar = client.get("/api/chat/sidebar").get_json()
    assert len(sidebar["agent_dms"]) == 1
    assert sidebar["agent_dms"][0]["hidden_from_roster"] is True

    assert client.get(f"/api/agents/{session_id}").status_code == 200

    r2 = client.post(f"/api/agents/{session_id}/hide-from-roster")
    assert r2.status_code == 200
