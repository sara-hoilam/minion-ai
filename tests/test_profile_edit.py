"""Test profile edit and resume management."""

from io import BytesIO

from backend.app import create_app


def test_profile_edit_and_resume_actions():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()

    client.post("/api/auth/register", json={"email": "edit@test.com", "password": "securepass1"})
    client.post("/api/profile/background", json={
        "full_name": "Jane Analyst",
        "field": "Data Analytics",
        "skillset": "SQL",
        "current_job": "Analyst",
        "years_experience": 3,
        "industry": "SaaS",
    })

    client.post(
        "/api/profile/resume",
        data={"resume": (BytesIO(b"<html><body><h1>CV</h1></body></html>"), "cv.html")},
        content_type="multipart/form-data",
    )

    r = client.put("/api/profile", json={
        "full_name": "Jane Updated",
        "current_job": "Senior Analyst",
        "field": "Data Science",
        "skillset": "SQL, Python",
        "years_experience": 5,
        "industry": "E-commerce",
    })
    assert r.status_code == 200
    assert r.get_json()["profile"]["full_name"] == "Jane Updated"

    r = client.get("/api/profile/resume/view")
    assert r.status_code == 200

    r = client.delete("/api/profile/resume")
    assert r.status_code == 200

    r = client.get("/api/home")
    assert r.get_json()["user"]["resume"]["has_resume"] is False
