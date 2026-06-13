"""Keep tests offline — do not call the live Cursor API during pytest."""

import pytest


@pytest.fixture(autouse=True)
def local_auth_unless_supabase_tests(request, monkeypatch):
    """Avoid live Supabase signup during generic tests when .env has keys configured."""
    if request.module.__name__.endswith("test_supabase_auth"):
        return
    disabled = lambda: False
    monkeypatch.setattr("backend.routes.auth.supabase_auth_enabled", disabled)
    monkeypatch.setattr("backend.services.supabase_auth.supabase_auth_enabled", disabled)


@pytest.fixture(autouse=True)
def sync_chat_generation(monkeypatch):
    """Run chat generation inline so sqlite :memory: works in tests."""

    def _sync_start(
        flask_app,
        thread_id,
        user_id,
        session_id,
        content,
        history,
        combined_context,
        cloud_agent_id,
        generation_seq,
        approved_plan=None,
        user_feedback=None,
        revision_round=0,
    ):
        from backend.services.chat_generation import _generation_worker

        _generation_worker(
            flask_app,
            thread_id,
            user_id,
            session_id,
            content,
            history,
            combined_context,
            cloud_agent_id,
            generation_seq,
            approved_plan,
            user_feedback,
            revision_round,
        )

    monkeypatch.setattr("backend.routes.chat.start_generation", _sync_start)


@pytest.fixture(autouse=True)
def bypass_token_budget_in_tests(monkeypatch, request):
    """Chat tests don't set up subscriptions; billing tests opt out via module name."""
    mod = getattr(request.module, "__name__", "")
    if "billing" in mod:
        return
    monkeypatch.setattr(
        "backend.services.subscription_service.ensure_token_budget",
        lambda user, cost: (True, None),
    )


@pytest.fixture(autouse=True)
def disable_live_cursor_api(monkeypatch):
    monkeypatch.setattr("backend.services.cursor_llm.CURSOR_API_KEY", "")
    monkeypatch.setattr("backend.services.cursor_llm.is_configured", lambda: False)
    monkeypatch.setattr("backend.services.cursor_llm.complete", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.services.cursor_llm.chat", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr("backend.services.chat_orchestrator.cursor_complete", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "backend.services.chat_orchestrator.cursor_chat",
        lambda *args, **kwargs: (None, args[1] if len(args) > 4 else None),
    )
    monkeypatch.setattr("backend.services.agent_jd_generator.cursor_complete", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.services.agent_jd_generator.cursor_configured", lambda: False)
    monkeypatch.setattr("backend.services.agent_framework_designer.cursor_complete", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.services.agent_framework_designer.cursor_configured", lambda: False)
    try:
        import backend.app as app_mod
        monkeypatch.setattr(app_mod, "cursor_llm_configured", lambda: False)
    except ImportError:
        pass
