"""End-to-end studio flow integration test."""

from io import BytesIO

from backend.app import create_app


def _register_and_background(client):
    r = client.post("/api/auth/register", json={
        "email": "analyst@test.com",
        "password": "securepass1",
    })
    assert r.status_code == 201

    return client.post("/api/profile/background", json={
        "full_name": "Jane Analyst",
        "field": "Data Analytics",
        "skillset": "SQL, Python, funnel analysis",
        "current_job": "Senior Data Analyst",
        "years_experience": 5,
        "industry": "E-commerce",
    })


def _test_client():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    return app.test_client()


def test_agent_created_after_one_task():
    client = _test_client()
    with client.application.app_context():

        assert _register_and_background(client).status_code == 200
        assert client.post("/api/studio/start").status_code == 200

        r = client.post("/api/studio/task/submit", json={
            "task_id": "investigation_scenario",
            "response_data": {
                "steps": "1. Check pipeline\n2. Segment by channel",
                "reasoning": "Rule out technical issues first",
            },
            "time_spent_seconds": 90,
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["agent_ready"] is True
        assert data["tasks_completed"] == 1
        assert data["session_status"] == "in_progress"
        assert data["has_more_tasks"] is True

        r = client.get("/api/studio/artifacts")
        artifacts = r.get_json()
        assert len(artifacts) == 2

        r = client.get("/api/studio/session")
        session = r.get_json()
        assert session["status"] == "agent_ready"
        assert session["has_more_tasks"] is True


def test_full_studio_flow():
    client = _test_client()
    with client.application.app_context():

        assert _register_and_background(client).status_code == 200
        assert client.post("/api/studio/start").status_code == 200

        tasks = [
            {
                "task_id": "investigation_scenario",
                "response_data": {
                    "steps": "1. Check data pipeline\n2. Segment by channel\n3. Compare YoY",
                    "reasoning": "Rule out technical issues first",
                },
            },
            {
                "task_id": "sql_challenge",
                "response_data": {
                    "sql": "SELECT date_trunc('week', event_timestamp) AS week, COUNT(DISTINCT user_id) AS wau FROM events GROUP BY 1",
                    "approach_notes": "Filter to last 8 weeks in outer query",
                },
            },
            {
                "task_id": "interpret_results",
                "response_data": {
                    "takeaway": "Activation is the bottleneck",
                    "recommendation": "Audit onboarding steps 2-3",
                    "confidence": "High",
                },
            },
            {
                "task_id": "stakeholder_communication",
                "response_data": {
                    "structure": "Headline metrics, then funnel, then risks",
                    "issue_flagging": "Red/yellow/green against targets",
                    "tone": "Concise & data-forward",
                },
            },
            {
                "task_id": "methodology_choice",
                "response_data": {
                    "method": "A/B test",
                    "rationale": "Clean randomization available",
                    "data_needed": "User assignments and retention flags",
                },
            },
        ]

        for task in tasks:
            r = client.post("/api/studio/task/submit", json={**task, "time_spent_seconds": 120})
            assert r.status_code == 200

        final = r.get_json()
        assert final["session_status"] == "completed"

        r = client.get("/api/studio/artifacts")
        artifacts = r.get_json()
        assert len(artifacts) == 2

        r = client.get(f"/api/studio/artifacts/{artifacts[0]['id']}/content")
        assert r.status_code == 200
        assert len(r.get_json()["content"]) > 100


def test_resume_upload_autofill():
    client = _test_client()
    with client.application.app_context():
        r = client.post("/api/auth/register", json={
            "email": "resume@test.com",
            "password": "securepass1",
        })
        assert r.status_code == 201

        html_resume = b"""
        <html><body>
        <h1>Jane Analyst</h1>
        <p>Senior Data Analyst</p>
        <h2>Skills</h2>
        <p>SQL, Python, Tableau, A/B testing</p>
        <p>5 years of experience in analytics</p>
        </body></html>
        """

        r = client.post(
            "/api/profile/resume",
            data={"resume": (BytesIO(html_resume), "resume.html")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        assert data["autofill"]["full_name"] == "Jane Analyst"
        assert "SQL" in (data["autofill"]["skillset"] or "")

        r = client.get("/api/profile/resume")
        assert r.get_json()["has_resume"] is True
