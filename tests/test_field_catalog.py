"""Field catalog and multi-agent session context."""

from backend.app import create_app


def test_catalog_endpoint():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    client = app.test_client()

    r = client.get("/api/profile/catalog")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data["fields"]) >= 10
    assert "Data Analytics" in [f["label"] for f in data["fields"]]
    assert "SQL" in data["skills_by_field"]["data_analytics"]


def test_create_agent_stores_context():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()

    client.post("/api/auth/register", json={"email": "multi@test.com", "password": "securepass1", "first_name": "Test", "last_name": "User"})
    client.post("/api/profile/background", json={
        "full_name": "Marketing Bot",
        "field": "Marketing",
        "skillset": "SEO, Content strategy",
        "current_job": "Marketing Manager",
        "industry": "SaaS",
    })

    jd = {
        "title": "Financial Analyst — Finance Bot",
        "summary": "Healthcare FP&A agent.",
        "responsibilities": ["Forecasting", "Variance analysis"],
    }

    r = client.post("/api/agents/create", json={
        "full_name": "Finance Bot",
        "field": "Finance",
        "industry": "Healthcare",
        "skillset": "FP&A, Forecasting",
        "current_job": "Financial Analyst",
        "job_description": jd,
        "framework_design": {"framework": {"orchestrator": {}, "agents": []}, "construction_answers": {}},
    })
    assert r.status_code == 200

    from backend.models import StudioSession
    with app.app_context():
        session = StudioSession.query.order_by(StudioSession.id.desc()).first()
        assert session.agent_context["field"] == "Finance"
        assert session.agent_context["full_name"] == "Finance Bot"
        assert session.status == "configured"
