"""Agent creation from personalization (no Studio assessment)."""

from pathlib import Path

from backend.app import create_app


def test_jd_draft_endpoint():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()

    client.post("/api/auth/register", json={"email": "val@test.com", "password": "securepass1", "first_name": "Test", "last_name": "User"})

    r = client.post("/api/agents/jd-draft", json={
        "full_name": "Ops Bot",
        "field": "Operations",
        "skillset": "Process improvement, KPI dashboards",
        "current_job": "Operations Manager",
        "industry": "SaaS",
    })
    assert r.status_code == 200
    data = r.get_json()
    jd = data["job_description"]
    assert jd["title"]
    assert len(jd["responsibilities"]) >= 3
    assert "day_to_day" not in data
    assert "questions" not in data


def test_framework_preview_skill_based():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()

    client.post("/api/auth/register", json={"email": "fw@test.com", "password": "securepass1", "first_name": "Test", "last_name": "User"})

    jd = {
        "title": "Analyst — Data Bot",
        "summary": "AI analyst for SaaS metrics.",
        "responsibilities": [
            "Own weekly KPI reporting with SQL",
            "Investigate metric anomalies",
            "Communicate findings in executive slide decks",
        ],
    }

    r = client.post("/api/agents/framework-preview", json={
        "full_name": "Data Bot",
        "field": "Data Analytics",
        "skillset": "SQL, Tableau",
        "current_job": "Data Analyst",
        "industry": "SaaS",
        "job_description": jd,
    })
    assert r.status_code == 200
    data = r.get_json()
    fw = data["framework"]

    assert fw["manager"]["id"] == "manager"
    assert len(fw["skill_breakdown"]) >= 2
    skill_agents = [a for a in fw["agents"] if a.get("type") == "skill"]
    assert len(skill_agents) >= 2
    assert len(skill_agents) <= max(len(jd["responsibilities"]), 6)
    assert all(a.get("skill_md") for a in fw["agents"])
    assert len(fw["interactions"]) >= 2
    assert isinstance(data["construction_questions"], list)
    assert data["job_description_used"]["title"] == jd["title"]


def test_framework_preview_uses_edited_jd():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "edit@test.com", "password": "securepass1", "first_name": "Test", "last_name": "User"})

    jd = {
        "title": "Custom Editor Title — My Bot",
        "summary": "User-edited summary for routing.",
        "responsibilities": [
            "Ship weekly executive dashboards",
            "Audit data pipelines for compliance",
            "Run ad-hoc board prep analyses",
            "Maintain forecasting models",
            "Coordinate with finance on close",
        ],
    }

    r = client.post("/api/agents/framework-preview", json={
        "full_name": "My Bot",
        "field": "Data Analytics",
        "skillset": "SQL, Python, Tableau, dbt, Looker, Excel",
        "current_job": "Data Analyst",
        "industry": "SaaS",
        "job_description": jd,
    })
    assert r.status_code == 200
    data = r.get_json()
    orch = data["framework"]["orchestrator"]["description"]
    assert "Custom Editor Title" in orch
    assert data["job_description_used"]["summary"] == jd["summary"]

    if data["construction_questions"]:
        q = data["construction_questions"][0]
        assert len(q["options"]) == 4
        assert {o["id"] for o in q["options"]} == {"A", "B", "C", "D"}
        assert q.get("allow_manual") is True


def test_framework_preview_job_returns_progress():
    import time

    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "job@test.com", "password": "securepass1", "first_name": "Test", "last_name": "User"})

    jd = {
        "title": "Analyst — Job Bot",
        "summary": "Metrics and reporting.",
        "responsibilities": [
            "Own weekly KPI reporting with SQL",
            "Investigate metric anomalies",
        ],
    }
    start = client.post("/api/agents/framework-preview/jobs", json={
        "full_name": "Job Bot",
        "field": "Data Analytics",
        "skillset": "SQL, Tableau",
        "current_job": "Data Analyst",
        "industry": "SaaS",
        "job_description": jd,
    })
    assert start.status_code == 202
    job_id = start.get_json()["job_id"]

    result = None
    for _ in range(40):
        status = client.get(f"/api/agents/framework-preview/jobs/{job_id}")
        assert status.status_code == 200
        data = status.get_json()
        assert "percent" in data
        assert isinstance(data.get("logs"), list)
        if data["status"] == "complete":
            result = data["result"]
            break
        if data["status"] == "failed":
            raise AssertionError(data.get("error"))
        time.sleep(0.15)

    assert result is not None
    assert result["framework"]["manager"]["id"] == "manager"
    assert data["percent"] == 100


def test_create_agent_writes_named_skill_and_framework_files():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()

    client.post("/api/auth/register", json={"email": "agent@test.com", "password": "securepass1", "first_name": "Test", "last_name": "User"})
    client.post("/api/profile/background", json={
        "full_name": "Finance Bot",
        "field": "Finance",
        "skillset": "FP&A, Forecasting",
        "current_job": "Financial Analyst",
        "industry": "Healthcare",
    })

    jd = {
        "title": "Financial Analyst — Finance Bot",
        "summary": "FP&A agent for healthcare finance.",
        "responsibilities": ["Build forecasts", "Variance analysis"],
    }
    fw = client.post("/api/agents/framework-preview", json={
        "full_name": "Finance Bot",
        "field": "Finance",
        "skillset": "FP&A, Forecasting",
        "current_job": "Financial Analyst",
        "industry": "Healthcare",
        "job_description": jd,
    }).get_json()

    r = client.post("/api/agents/create", json={
        "full_name": "Finance Bot",
        "field": "Finance",
        "skillset": "FP&A, Forecasting",
        "current_job": "Financial Analyst",
        "industry": "Healthcare",
        "job_description": jd,
        "framework_design": {
            "framework": fw["framework"],
            "construction_answers": {},
        },
    })
    assert r.status_code == 200
    session_id = r.get_json()["session_id"]

    home = client.get("/api/home").get_json()
    assert len(home["personas"]) == 1
    assert home["personas"][0]["name"] == "Finance Bot"

    from backend.config import AGENT_OUTPUT_FOLDER

    user_dir = Path(AGENT_OUTPUT_FOLDER) / "1"
    skill_path = user_dir / "finance_bot_skill.md"
    framework_path = user_dir / "finance_bot_agent_framework.json"
    assert skill_path.exists()
    assert framework_path.exists()
    assert "Skill specifications: Finance Bot" in skill_path.read_text(encoding="utf-8")
    assert '"profile_name": "Finance Bot"' in framework_path.read_text(encoding="utf-8")

    download = client.get(f"/api/studio/artifacts/{home['personas'][0]['artifacts']['framework_json_id']}/download")
    assert download.status_code == 200
    assert "finance_bot_agent_framework.json" in download.headers.get("Content-Disposition", "")

    skill_id = home["personas"][0]["artifacts"].get("skill_md_id")
    if skill_id:
        skill_dl = client.get(f"/api/studio/artifacts/{skill_id}/download")
        assert skill_dl.status_code == 200
        assert "finance_bot_skill.md" in skill_dl.headers.get("Content-Disposition", "")


def test_update_agent_skills_rebuilds_framework():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "skills@test.com", "password": "securepass1", "first_name": "Test", "last_name": "User"})

    jd = {
        "title": "Analyst — Riley",
        "summary": "Finance agent.",
        "responsibilities": ["Build forecasts", "Report to board"],
    }
    fw = client.post("/api/agents/framework-preview", json={
        "full_name": "Riley",
        "field": "Finance",
        "skillset": "FP&A, reporting",
        "current_job": "Analyst",
        "industry": "SaaS",
        "job_description": jd,
    }).get_json()
    session_id = client.post("/api/agents/create", json={
        "full_name": "Riley",
        "field": "Finance",
        "skillset": "FP&A, reporting",
        "current_job": "Analyst",
        "industry": "SaaS",
        "job_description": jd,
        "framework_design": {"framework": fw["framework"], "construction_answers": {}},
    }).get_json()["session_id"]

    res = client.put(
        f"/api/agents/{session_id}/skills",
        json={"skills": ["Cash flow", "P&L management", "Valuation"]},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert "Cash flow" in body["skillset"]
    assert len(body.get("subagents") or []) >= 2

    agent = client.get(f"/api/agents/{session_id}").get_json()
    skill_agents = [
        a for a in agent["framework_design"]["framework"]["agents"]
        if a.get("type") == "skill"
    ]
    skill_names = [a.get("skill") for a in skill_agents]
    assert "Cash flow" in skill_names
    assert "P&L management" in skill_names
    assert "Valuation" in skill_names


def test_framework_preview_rejects_excess_skills():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "cap@test.com", "password": "securepass1", "first_name": "Test", "last_name": "User"})

    jd = {
        "title": "Analyst — Cap Bot",
        "summary": "Many skills.",
        "responsibilities": ["Task A", "Task B"],
    }
    too_many = ", ".join(f"Skill {i}" for i in range(10))
    r = client.post("/api/agents/framework-preview", json={
        "full_name": "Cap Bot",
        "field": "Operations",
        "skillset": too_many,
        "current_job": "Analyst",
        "industry": "SaaS",
        "job_description": jd,
    })
    assert r.status_code == 400
    assert "Maximum 8 skills" in r.get_json()["error"]


def test_framework_preview_accepts_updated_skillset():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "skills@test.com", "password": "securepass1", "first_name": "Test", "last_name": "User"})

    jd = {
        "title": "Analyst — Skills Bot",
        "summary": "Skill updates on framework step.",
        "responsibilities": ["Analyze data", "Build dashboards"],
    }
    base = {
        "full_name": "Skills Bot",
        "field": "Data Analytics",
        "current_job": "Analyst",
        "industry": "SaaS",
        "job_description": jd,
    }

    first = client.post("/api/agents/framework-preview", json={
        **base,
        "skillset": "SQL, Tableau",
    })
    assert first.status_code == 200
    first_agents = [
        a.get("skill") for a in first.get_json()["framework"]["agents"]
        if a.get("type") == "skill"
    ]
    assert "SQL" in first_agents
    assert "Tableau" in first_agents

    updated = client.post("/api/agents/framework-preview", json={
        **base,
        "skillset": "SQL, Python, Business acumen",
    })
    assert updated.status_code == 200
    updated_agents = [
        a.get("skill") for a in updated.get_json()["framework"]["agents"]
        if a.get("type") == "skill"
    ]
    assert "Python" in updated_agents
    assert "Business acumen" in updated_agents
    assert "Tableau" not in updated_agents


def test_framework_preview_uses_user_skills_without_ai(monkeypatch):
    from backend.services import agent_framework_designer as designer

    ai_called = {"count": 0}

    def _fake_ai(*args, **kwargs):
        ai_called["count"] += 1
        return None

    monkeypatch.setattr(designer, "cursor_configured", lambda: True)
    monkeypatch.setattr(designer, "cursor_complete", _fake_ai)

    jd = {
        "title": "Analyst — Fast Bot",
        "summary": "Uses selected skills only.",
        "responsibilities": [
            "Write SQL for KPI reporting",
            "Build executive slide decks",
        ],
    }
    context = {
        "full_name": "Fast Bot",
        "field": "Data Analytics",
        "skillset": "SQL, Tableau, Business acumen",
        "current_job": "Analyst",
        "industry": "SaaS",
    }
    result = designer.generate_framework_preview(jd, context)
    assert ai_called["count"] == 0
    assert result["source"] == "template"
    skill_agents = [
        a for a in result["framework"]["agents"]
        if a.get("type") == "skill"
    ]
    assert len(skill_agents) == 3
