"""Auth behavior in dev mode (DISABLE_AUTH)."""

from backend.app import create_app


def test_login_bypasses_credentials_when_auth_disabled():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": True,
    })
    client = app.test_client()

    r = client.post("/api/auth/login", json={
        "email": "wrong@example.com",
        "password": "not-the-password",
    })
    assert r.status_code == 200
    data = r.get_json()
    assert data["email"] == "demo@minion.ai"

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.get_json()["email"] == "demo@minion.ai"


def test_demo_user_exists_for_real_login():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()

    r = client.post("/api/auth/login", json={
        "email": "demo@minion.ai",
        "password": "demo",
    })
    assert r.status_code == 200
    assert r.get_json()["email"] == "demo@minion.ai"
