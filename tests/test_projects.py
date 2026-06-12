"""Project workspace API — CRUD, files, project_agent threads."""

import io

from backend.app import create_app


def _create_agent(client, name="Alex"):
    client.post("/api/profile/background", json={
        "full_name": name,
        "field": "Finance",
        "skillset": "FP&A, SQL",
        "current_job": "Analyst",
        "industry": "SaaS",
    })
    jd = {
        "title": f"Analyst — {name}",
        "summary": "Finance agent.",
        "responsibilities": ["Build forecasts", "Analyze data"],
    }
    fw = client.post("/api/agents/framework-preview", json={
        "full_name": name,
        "field": "Finance",
        "skillset": "FP&A, SQL",
        "current_job": "Analyst",
        "industry": "SaaS",
        "job_description": jd,
    }).get_json()
    return client.post("/api/agents/create", json={
        "full_name": name,
        "field": "Finance",
        "skillset": "FP&A, SQL",
        "current_job": "Analyst",
        "industry": "SaaS",
        "job_description": jd,
        "framework_design": {"framework": fw["framework"], "construction_answers": {}},
    }).get_json()["session_id"]


def _app_client():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
        "TESTING": True,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "projects@test.com", "password": "securepass1"})
    return app, client


def test_list_and_create_project():
    _, client = _app_client()
    session_id = _create_agent(client, "Morgan")

    listed = client.get("/api/projects").get_json()
    assert listed["projects"] == []

    created = client.post("/api/projects", json={
        "name": "Q2 Analysis",
        "instructions": "Focus on revenue trends",
        "agent_session_ids": [session_id],
    }).get_json()
    assert created["name"] == "Q2 Analysis"
    assert session_id in created["agent_session_ids"]
    assert len(created["agents"]) == 1
    assert created["agents"][0]["thread_id"]

    listed = client.get("/api/projects").get_json()
    assert len(listed["projects"]) == 1


def test_project_agent_thread_separate_from_dm():
    _, client = _app_client()
    session_id = _create_agent(client, "Jordan")

    project = client.post("/api/projects", json={
        "name": "Project A",
        "agent_session_ids": [session_id],
    }).get_json()

    dm = client.post("/api/chat/threads", json={
        "agent_session_id": session_id,
        "thread_type": "agent_dm",
    }).get_json()

    project_thread = client.post("/api/chat/threads", json={
        "thread_type": "project_agent",
        "project_id": project["id"],
        "agent_session_id": session_id,
    }).get_json()

    assert dm["id"] != project_thread["id"]
    assert project_thread["thread_type"] == "project_agent"
    assert project_thread["project_id"] == project["id"]

    again = client.post("/api/chat/threads", json={
        "thread_type": "project_agent",
        "project_id": project["id"],
        "agent_session_id": session_id,
    }).get_json()
    assert again["id"] == project_thread["id"]


def test_upload_project_file_to_storage():
    _, client = _app_client()
    project = client.post("/api/projects", json={"name": "Files test"}).get_json()

    data = {
        "file": (io.BytesIO(b"col1,col2\n1,2\n"), "data.csv"),
    }
    res = client.post(
        f"/api/projects/{project['id']}/files",
        data=data,
        content_type="multipart/form-data",
    )
    assert res.status_code == 200
    body = res.get_json()
    assert len(body["context_files"]) == 1
    assert body["context_files"][0]["storage_path"]
    assert "path" not in body["context_files"][0] or not body["context_files"][0].get("path", "").startswith("uploads")

    deleted = client.delete(f"/api/projects/{project['id']}/files/0")
    assert deleted.status_code == 200
    assert deleted.get_json()["context_files"] == []
