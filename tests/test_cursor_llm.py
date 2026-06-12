"""Cursor LLM configuration and prompt helpers."""

from backend.app import create_app
from backend.services import cursor_llm


def test_cursor_key_loads_from_env(monkeypatch):
    import importlib

    import backend.config as config_mod

    monkeypatch.setenv("CURSOR_API_KEY", "crsr_test_key")
    importlib.reload(config_mod)
    assert config_mod.CURSOR_API_KEY == "crsr_test_key"


def test_build_prompt_includes_system_and_history():
    prompt = cursor_llm._build_prompt(
        "You are a finance agent.",
        "What is churn?",
        [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}],
    )
    assert "SYSTEM INSTRUCTIONS" in prompt
    assert "CONVERSATION HISTORY" in prompt
    assert "What is churn?" in prompt


def test_api_config_reports_cursor_llm(monkeypatch):
    import backend.app as app_mod
    monkeypatch.setattr(app_mod, "cursor_llm_configured", lambda: True)
    monkeypatch.setattr(app_mod, "CURSOR_MODEL", "composer-2.5")
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": True,
    })
    client = app.test_client()
    data = client.get("/api/config").get_json()
    assert data["llm"]["provider"] == "cursor"
    assert data["llm"]["model"] == "composer-2.5"
    assert data["llm"]["configured"] is True
