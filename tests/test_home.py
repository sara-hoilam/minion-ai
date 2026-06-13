"""Test home dashboard API."""

from io import BytesIO

from backend.app import create_app


def test_home_dashboard_with_persona():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()

    client.post("/api/auth/register", json={"email": "home@test.com", "password": "securepass1", "first_name": "Test", "last_name": "User"})
    client.post("/api/profile/background", json={
        "full_name": "Jane Analyst",
        "field": "Data Analytics",
        "skillset": "SQL, Python, Tableau",
        "current_job": "Senior Data Analyst",
        "years_experience": 5,
        "industry": "SaaS",
    })

    client.post(
        "/api/profile/resume",
        data={"resume": (BytesIO(b"<html><body><h1>Jane</h1></body></html>"), "cv.html")},
        content_type="multipart/form-data",
    )

    client.post("/api/studio/start")
    client.post("/api/studio/task/submit", json={
        "task_id": "investigation_scenario",
        "response_data": {"steps": "Check pipeline", "reasoning": "First rule out bugs"},
        "time_spent_seconds": 60,
    })

    r = client.get("/api/home")
    assert r.status_code == 200
    data = r.get_json()

    assert data["user"]["full_name"] == "Jane Analyst"
    assert data["user"]["resume"]["has_resume"] is True
    assert len(data["personas"]) == 1
    assert data["personas"][0]["name"] == "Jane Analyst"
    assert "SQL" in data["personas"][0]["skills"][0]
    assert data["personas"][0]["framework"] is not None
    assert len(data["personas"][0]["framework"]["agents"]) > 0
