"""Supabase Auth integration (mocked — no live Supabase in CI)."""

from backend.app import create_app
from backend.models import User, db
from backend.services.supabase_auth import SupabaseAuthResult


def test_register_uses_supabase_when_configured(monkeypatch):
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_ANON_KEY": "test-anon-key",
    })
    client = app.test_client()

    def fake_sign_up(email, password, *, first_name="", last_name=""):
        assert email == "new@test.com"
        assert first_name == "Jane"
        assert last_name == "Doe"
        return SupabaseAuthResult(
            supabase_user_id="11111111-1111-1111-1111-111111111111",
            email=email,
            access_token="access",
            refresh_token="refresh",
        )

    monkeypatch.setattr("backend.routes.auth.supabase_sign_up", fake_sign_up)
    monkeypatch.setattr("backend.routes.auth.supabase_auth_enabled", lambda: True)
    monkeypatch.setattr("backend.routes.auth.find_supabase_auth_user", lambda email: None)

    r = client.post("/api/auth/register", json={
        "email": "new@test.com",
        "password": "securepass1",
        "first_name": "Jane",
        "last_name": "Doe",
    })
    assert r.status_code == 201
    with app.app_context():
        user = User.query.filter_by(email="new@test.com").first()
        assert user is not None
        assert user.supabase_auth_id == "11111111-1111-1111-1111-111111111111"
        assert user.profile.first_name == "Jane"
        assert user.profile.last_name == "Doe"


def test_login_uses_supabase_when_configured(monkeypatch):
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_ANON_KEY": "test-anon-key",
    })
    client = app.test_client()

    def fake_sign_in(email, password):
        return SupabaseAuthResult(
            supabase_user_id="22222222-2222-2222-2222-222222222222",
            email=email,
            access_token="access",
            refresh_token="refresh",
        )

    monkeypatch.setattr("backend.routes.auth.supabase_sign_in", fake_sign_in)
    monkeypatch.setattr("backend.routes.auth.supabase_auth_enabled", lambda: True)

    r = client.post("/api/auth/login", json={
        "email": "user@test.com",
        "password": "securepass1",
    })
    assert r.status_code == 200
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.get_json()["auth_provider"] == "supabase"


def test_login_redirects_to_register_when_email_missing(monkeypatch):
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_ANON_KEY": "test-anon-key",
    })
    client = app.test_client()

    def fake_sign_in(email, password):
        raise ValueError("Invalid credentials")

    monkeypatch.setattr("backend.routes.auth.supabase_sign_in", fake_sign_in)
    monkeypatch.setattr("backend.routes.auth.supabase_auth_enabled", lambda: True)
    monkeypatch.setattr("backend.routes.auth.find_supabase_auth_user", lambda email: None)
    monkeypatch.setattr("backend.routes.auth.auth_user_exists", lambda email: False)

    r = client.post("/api/auth/login", json={
        "email": "missing@test.com",
        "password": "securepass1",
    })
    assert r.status_code == 404
    data = r.get_json()
    assert data["redirect"] == "register"
    assert data["email"] == "missing@test.com"


def test_register_rejects_password_mismatch():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    r = client.post("/api/auth/register", json={
        "email": "new@test.com",
        "password": "securepass1",
        "password_confirm": "different1",
        "first_name": "Test",
        "last_name": "User",
    })
    assert r.status_code == 400
    assert "match" in r.get_json()["error"].lower()


def test_register_requires_names():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    r = client.post("/api/auth/register", json={
        "email": "new@test.com",
        "password": "securepass1",
    })
    assert r.status_code == 400
    assert "name" in r.get_json()["error"].lower()


def test_register_saves_names_locally():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
        "SUPABASE_URL": "",
        "SUPABASE_ANON_KEY": "",
    })
    client = app.test_client()
    r = client.post("/api/auth/register", json={
        "email": "local@test.com",
        "password": "securepass1",
        "first_name": "Alex",
        "last_name": "Smith",
    })
    assert r.status_code == 201
    with app.app_context():
        user = User.query.filter_by(email="local@test.com").first()
        assert user.profile.first_name == "Alex"
        assert user.profile.last_name == "Smith"
        assert user.profile.full_name == "Alex Smith"
    me = client.get("/api/auth/me").get_json()
    assert me["profile"]["first_name"] == "Alex"
    assert me["profile"]["last_name"] == "Smith"


def test_reset_password_syncs_user_and_logs_in(monkeypatch):
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_ANON_KEY": "test-anon-key",
    })
    client = app.test_client()

    monkeypatch.setattr("backend.routes.auth.supabase_auth_enabled", lambda: True)
    monkeypatch.setattr("backend.routes.auth.update_password", lambda token, pwd: {"ok": True})
    monkeypatch.setattr("backend.routes.auth.get_user_from_token", lambda token: {
        "id": "33333333-3333-3333-3333-333333333333",
        "email": "user@test.com",
    })

    r = client.post("/api/auth/reset-password", json={
        "access_token": "recovery-token",
        "refresh_token": "refresh-token",
        "password": "newsecure1",
        "password_confirm": "newsecure1",
    })
    assert r.status_code == 200
    with app.app_context():
        user = User.query.filter_by(email="user@test.com").first()
        assert user is not None
        assert user.supabase_auth_id == "33333333-3333-3333-3333-333333333333"
    me = client.get("/api/auth/me")
    assert me.status_code == 200


def test_config_reports_supabase_provider():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_ANON_KEY": "test-anon-key",
    })
    client = app.test_client()
    cfg = client.get("/api/config").get_json()
    assert cfg["auth_provider"] == "supabase"
