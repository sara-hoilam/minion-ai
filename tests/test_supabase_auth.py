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

    def fake_sign_up(email, password):
        assert email == "new@test.com"
        return SupabaseAuthResult(
            supabase_user_id="11111111-1111-1111-1111-111111111111",
            email=email,
            access_token="access",
            refresh_token="refresh",
        )

    monkeypatch.setattr("backend.routes.auth.supabase_sign_up", fake_sign_up)
    monkeypatch.setattr("backend.routes.auth.supabase_auth_enabled", lambda: True)

    r = client.post("/api/auth/register", json={
        "email": "new@test.com",
        "password": "securepass1",
    })
    assert r.status_code == 201
    with app.app_context():
        user = User.query.filter_by(email="new@test.com").first()
        assert user is not None
        assert user.supabase_auth_id == "11111111-1111-1111-1111-111111111111"


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


def test_config_reports_supabase_provider():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_ANON_KEY": "test-anon-key",
    })
    client = app.test_client()
    cfg = client.get("/api/config").get_json()
    assert cfg["auth_provider"] == "supabase"
