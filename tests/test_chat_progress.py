"""Live chat generation progress and cancellation."""

from backend.app import create_app
from backend.models import ChatThread, User, db
from backend.services.chat_orchestrator import run_agent_turn
from backend.services.chat_progress import (
    ChatGenerationCancelled,
    ChatProgressReporter,
    build_delegation_decision_thoughts,
    build_subagent_thought_chain,
    finalize_planning_thought_chain,
    thought_meta_from_progress,
)
from backend.services.skill_framework import build_skill_framework


def _framework():
    jd = {
        "title": "Analyst — Test",
        "summary": "Finance analyst agent.",
        "responsibilities": ["Build forecasts", "Query data warehouses"],
    }
    context = {
        "full_name": "Sara",
        "field": "Finance",
        "industry": "SaaS",
        "current_job": "Financial Analyst",
        "skillset": "SQL, FP&A",
    }
    return build_skill_framework(jd, context)["framework"], context


def _thread_in_app(app):
    with app.app_context():
        user = User(email="prog@test.com", password_hash="hashed")
        db.session.add(user)
        db.session.flush()
        thread = ChatThread(user_id=user.id, thread_type="agent_dm", title="Chat")
        db.session.add(thread)
        db.session.commit()
        return thread.id


def test_thought_meta_from_progress_builds_chain_and_duration():
    meta = thought_meta_from_progress({
        "thought_chain": ["Reading your message", "Drafting answer"],
        "manager_plan": "Direct reply.",
        "started_at": "2026-06-12T10:00:00+00:00",
        "steps": [{"label": "Reasoning", "status": "done"}],
    })
    assert meta is not None
    assert meta["thoughts"][0] == "Direct reply."
    assert len(meta["thoughts"]) >= 3
    assert meta["duration_sec"] >= 1


def test_thought_meta_from_progress_returns_none_when_empty():
    assert thought_meta_from_progress({}) is None
    assert thought_meta_from_progress({"thoughts": []}) is None


def test_update_delegation_thinking_reveals_subagent_chain():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    thread_id = _thread_in_app(app)

    with app.app_context():
        thread = db.session.get(ChatThread, thread_id)
        thread.generation_seq = 1
        thread.is_generating = True
        db.session.commit()
        reporter = ChatProgressReporter(thread_id, 1)
        reporter.begin_planning("Sara", "Analyze funnel metrics", [{"skill": "SQL query"}])
        reporter.set_manager_plan("Plan ready.", [{"skill": "SQL query", "task": "Pull metrics"}])
        reporter.step_active(0, {"skill": "SQL query", "task": "Pull metrics"})

        before = len(reporter.snapshot().get("thoughts") or [])
        reporter.update_delegation_thinking("RUNNING", 6.0)
        snap = reporter.snapshot()
        thoughts = snap.get("thoughts") or []
        assert len(thoughts) > before
        assert any("SQL query specialist" in t for t in thoughts)
        assert snap.get("phase_label")
        assert any(s.get("status") == "active" for s in snap.get("steps") or [])


def test_build_subagent_thought_chain_includes_skill_and_task():
    chain = build_subagent_thought_chain("Investor reporting", "Draft quarterly deck.")
    assert chain[0].startswith("Investor reporting specialist")
    assert "Draft quarterly deck" in chain[1]


def test_progress_reporter_tracks_team_steps():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    thread_id = _thread_in_app(app)

    with app.app_context():
        thread = db.session.get(ChatThread, thread_id)
        thread.generation_seq = 1
        thread.is_generating = True
        db.session.commit()
        reporter = ChatProgressReporter(thread_id, 1)
        reporter.begin_planning("Sara", "Analyze funnel metrics", [{"skill": "SQL query"}, {"skill": "Financial analysis"}])
        reporter.set_manager_plan("Plan ready.", [{"skill": "SQL query", "task": "Pull metrics"}])
        reporter.step_active(0, {"skill": "SQL query", "task": "Pull metrics"})
        snap = reporter.snapshot()
        assert snap["mode"] == "team_task"
        assert snap["manager_plan"] == "Plan ready."
        assert any(s.get("status") == "active" for s in snap["steps"])


def test_update_simple_thinking_accepts_poll_tick_signature():
    """cursor_llm._poll_run calls on_tick(status, elapsed_s) — must not raise."""
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    thread_id = _thread_in_app(app)

    with app.app_context():
        thread = db.session.get(ChatThread, thread_id)
        thread.generation_seq = 1
        thread.is_generating = True
        db.session.commit()
        reporter = ChatProgressReporter(thread_id, 1)
        reporter.begin_simple("Rayna", "What date is it today?", routing="direct")

        reporter.update_simple_thinking("CREATING", 0.5)
        reporter.update_simple_thinking("RUNNING", 4.5)
        reporter.update_simple_thinking("FINISHED", 12.0)

        snap = reporter.snapshot()
        assert snap["mode"] == "simple"
        thoughts = snap.get("thoughts") or []
        assert len(thoughts) >= 3
        assert not any("composer run" in t.lower() for t in thoughts)
        assert not any("(" in t and "s)" in t for t in thoughts)
        assert any("date" in t.lower() for t in thoughts)


def test_set_manager_plan_shows_delegation_decisions():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    thread_id = _thread_in_app(app)

    with app.app_context():
        thread = db.session.get(ChatThread, thread_id)
        thread.generation_seq = 1
        thread.is_generating = True
        db.session.commit()
        reporter = ChatProgressReporter(thread_id, 1)
        skill_agents = [
            {"id": "s1", "skill": "SQL query"},
            {"id": "s2", "skill": "Financial analysis"},
            {"id": "s3", "skill": "Report authoring"},
        ]
        reporter.begin_planning(
            "Rosalie",
            "Analyze funnel and prepare a summary report",
            skill_agents,
            matched_skills=[skill_agents[0], skill_agents[2]],
        )
        subtasks = [
            {"skill": "SQL query", "agent_id": "s1", "task": "Pull funnel metrics."},
            {"skill": "Report authoring", "agent_id": "s3", "task": "Draft executive summary."},
        ]
        reporter.set_manager_plan("Lean two-step plan.", subtasks, skill_agents)

        snap = reporter.snapshot()
        thoughts = " ".join(snap.get("thoughts") or [])
        assert "Delegation decisions" in thoughts
        assert "Step 1 → SQL query" in thoughts
        assert "Not delegating to Financial analysis" in thoughts
        assert any("Not delegating" in t for t in snap.get("thoughts") or [])
        assert not any("Skipping" in t for t in snap.get("thoughts") or [])
        assert snap.get("thought_chain") == snap.get("thoughts")


def test_finalize_planning_strips_contradictory_heuristic_skips():
    old_chain = [
        "Reading your message: «prepare investor deck»",
        "→ Investor reporting looks relevant — likely needed.",
        "✗ Skipping Scenario planning — not required for this scope.",
        "✗ Skipping Valuation — not required for this scope.",
        "Deciding assignments and execution order…",
    ]
    subtasks = [
        {"skill": "Scenario planning", "task": "Build scenarios."},
        {"skill": "Valuation", "task": "Run valuation."},
        {"skill": "Investor reporting", "task": "Draft deck."},
    ]
    roster = [
        {"skill": "Scenario planning"},
        {"skill": "Valuation"},
        {"skill": "Investor reporting"},
        {"skill": "Cash flow"},
    ]
    final = finalize_planning_thought_chain(old_chain, subtasks, roster)
    text = " ".join(final)
    assert "Skipping Scenario planning" not in text
    assert "looks relevant" not in text
    assert "Step 1 → Scenario planning" in text
    assert "Step 3 → Investor reporting" in text
    assert "Not delegating to Cash flow" in text


def test_thought_meta_prefers_reconciled_thoughts_over_stale_chain():
    meta = thought_meta_from_progress({
        "thought_chain": ["✗ Skipping Valuation — not required for this scope."],
        "thoughts": [
            "Delegation decisions:",
            "Step 1 → Valuation: Run DCF.",
            "Not delegating to Cash flow — outside scope for this request.",
        ],
        "started_at": "2026-06-12T10:00:00+00:00",
    })
    assert meta is not None
    assert "Skipping Valuation" not in " ".join(meta["thoughts"])
    assert "Step 1 → Valuation" in " ".join(meta["thoughts"])


def test_cancel_preserves_cloud_agent_id():
    from backend.models import ChatThread, db
    from backend.services.chat_generation import finalize_cancel

    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    thread_id = _thread_in_app(app)

    with app.app_context():
        thread = db.session.get(ChatThread, thread_id)
        thread.cursor_cloud_agent_id = "bc-test-agent-123"
        thread.is_generating = True
        thread.generation_seq = 2
        thread.active_cursor_run = {"agent_id": "bc-test-agent-123", "run_id": "run-123"}
        db.session.commit()

        finalize_cancel(thread_id, "Sara")

        row = db.session.get(ChatThread, thread_id)
        assert row.cursor_cloud_agent_id == "bc-test-agent-123"
        assert row.is_generating is False
        assert row.cancel_requested is False
        assert row.active_cursor_run is None


def test_run_agent_turn_raises_when_cancelled(monkeypatch):
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    framework, context = _framework()
    thread_id = _thread_in_app(app)

    with app.app_context():
        thread = db.session.get(ChatThread, thread_id)
        thread.generation_seq = 1
        thread.is_generating = True
        reporter = ChatProgressReporter(thread_id, 1)
        reporter.begin_planning("Sara", "Analyze funnel metrics", [{"skill": "SQL query"}, {"skill": "Financial analysis"}])
        thread.cancel_requested = True
        db.session.commit()

        monkeypatch.setattr("backend.services.chat_orchestrator.cursor_complete", lambda *a, **k: None)

        try:
            run_agent_turn(
                context,
                framework,
                "Analyze revenue migration funnel and prepare an executive summary report",
                progress=ChatProgressReporter(thread.id, thread.generation_seq or 1),
            )
            raised = False
        except ChatGenerationCancelled:
            raised = True

        assert raised is True
