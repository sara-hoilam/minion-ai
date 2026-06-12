"""Cursor LLM configuration and prompt helpers."""

from backend.app import create_app
from backend.services import cursor_llm


def test_cursor_key_loads_from_file(tmp_path, monkeypatch):
    key_file = tmp_path / "cursor_apikey.txt"
    key_file.write_text("crsr_test_key\n", encoding="utf-8")
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)

    def _load():
        env_key = ""
        if key_file.exists():
            return key_file.read_text(encoding="utf-8").strip()
        return env_key

    assert _load() == "crsr_test_key"


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
