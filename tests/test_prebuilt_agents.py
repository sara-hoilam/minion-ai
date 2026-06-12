"""Prebuilt agent catalog and add-to-workspace API."""

from backend.app import create_app


def _register(client):
    client.post("/api/auth/register", json={"email": "prebuilt@test.com", "password": "securepass1"})


def test_prebuilt_catalog_lists_agents():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    _register(client)

    r = client.get("/api/agents/prebuilt")
    assert r.status_code == 200
    agents = r.get_json()["agents"]
    assert len(agents) >= 10
    assert all("id" in a and "name" in a and "added" in a for a in agents)
    assert agents[0]["added"] is False


def test_prebuilt_catalog_search():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    _register(client)

    r = client.get("/api/agents/prebuilt?search=sql")
    assert r.status_code == 200
    agents = r.get_json()["agents"]
    assert len(agents) >= 1
    text = " ".join(
        f"{a['name']} {a.get('tagline', '')} {' '.join(a.get('skills') or [])}".lower()
        for a in agents
    )
    assert "sql" in text


def test_add_prebuilt_agent_to_workspace():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    _register(client)

    catalog = client.get("/api/agents/prebuilt").get_json()["agents"]
    template_id = catalog[0]["id"]

    r = client.post(f"/api/agents/prebuilt/{template_id}/add")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["session_id"]
    assert data["prebuilt_id"] == template_id

    session_id = data["session_id"]
    client.post("/api/chat/threads", json={"agent_session_id": session_id})

    sidebar = client.get("/api/chat/sidebar").get_json()
    assert len(sidebar["agent_dms"]) == 1
    assert sidebar["agent_dms"][0]["name"] == catalog[0]["name"]

    catalog_after = client.get("/api/agents/prebuilt").get_json()["agents"]
    added = next(a for a in catalog_after if a["id"] == template_id)
    assert added["added"] is True

    dup = client.post(f"/api/agents/prebuilt/{template_id}/add")
    assert dup.status_code == 409


def test_hidden_prebuilt_agent_not_marked_added():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    _register(client)

    catalog = client.get("/api/agents/prebuilt").get_json()["agents"]
    template_id = catalog[0]["id"]
    add = client.post(f"/api/agents/prebuilt/{template_id}/add").get_json()
    session_id = add["session_id"]
    client.post("/api/chat/threads", json={"agent_session_id": session_id})

    hide = client.post(f"/api/agents/{session_id}/hide-from-roster")
    assert hide.status_code == 200

    catalog_after_hide = client.get("/api/agents/prebuilt").get_json()["agents"]
    entry = next(a for a in catalog_after_hide if a["id"] == template_id)
    assert entry["added"] is False

    restore = client.post(f"/api/agents/prebuilt/{template_id}/add")
    assert restore.status_code == 200
    restored = restore.get_json()
    assert restored["session_id"] == session_id
    assert restored.get("restored") is True

    home = client.get("/api/home").get_json()
    assert len(home["personas"]) == 1

    sidebar = client.get("/api/chat/sidebar").get_json()
    dm = next(a for a in sidebar["agent_dms"] if a["session_id"] == session_id)
    assert dm["hidden_from_roster"] is False
