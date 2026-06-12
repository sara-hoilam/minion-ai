"""Chat workspace API — threads, messages, team task replies."""

import time

from backend.app import create_app


def _wait_thread_done(client, thread_id: int, timeout: float = 15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        loaded = client.get(f"/api/chat/threads/{thread_id}").get_json()
        if not loaded.get("is_generating"):
            return loaded
        time.sleep(0.05)
    raise AssertionError(f"Thread {thread_id} still generating after {timeout}s")


def _create_agent(client, name="Sara"):
    client.post("/api/profile/background", json={
        "full_name": name,
        "field": "Finance",
        "skillset": "FP&A, SQL, forecasting",
        "current_job": "Financial Analyst",
        "industry": "SaaS",
    })
    jd = {
        "title": f"Analyst — {name}",
        "summary": "Finance agent.",
        "responsibilities": ["Build forecasts", "Analyze funnel data", "Prepare reports"],
    }
    fw = client.post("/api/agents/framework-preview", json={
        "full_name": name,
        "field": "Finance",
        "skillset": "FP&A, SQL, forecasting",
        "current_job": "Financial Analyst",
        "industry": "SaaS",
        "job_description": jd,
    }).get_json()

    return client.post("/api/agents/create", json={
        "full_name": name,
        "field": "Finance",
        "skillset": "FP&A, SQL, forecasting",
        "current_job": "Financial Analyst",
        "industry": "SaaS",
        "job_description": jd,
        "framework_design": {
            "framework": fw["framework"],
            "construction_answers": {},
        },
    }).get_json()["session_id"]


def test_sidebar_includes_agent_without_dm_thread():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "sidebar@test.com", "password": "securepass1"})
    session_id = _create_agent(client, name="Richard")

    with app.app_context():
        from backend.models import ChatThread, db

        ChatThread.query.filter_by(agent_session_id=session_id).delete()
        db.session.commit()

    sidebar = client.get("/api/chat/sidebar").get_json()
    match = next(a for a in sidebar["agent_dms"] if a["session_id"] == session_id)
    assert match["name"] == "Richard"
    assert match["thread_id"] is None


def test_create_agent_creates_dm_thread():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "dm@test.com", "password": "securepass1"})
    session_id = _create_agent(client, name="Richard")

    with app.app_context():
        from backend.models import ChatThread

        thread = ChatThread.query.filter_by(agent_session_id=session_id, thread_type="agent_dm").first()
        assert thread is not None


def test_list_chat_agents():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "chat@test.com", "password": "securepass1"})
    session_id = _create_agent(client)

    r = client.get("/api/chat/agents")
    assert r.status_code == 200
    agents = r.get_json()["agents"]
    assert len(agents) == 1
    assert agents[0]["session_id"] == session_id
    assert agents[0]["name"] == "Sara"


def test_create_thread_welcome_message():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "thread@test.com", "password": "securepass1"})
    session_id = _create_agent(client)

    r = client.post("/api/chat/threads", json={"agent_session_id": session_id})
    assert r.status_code == 201
    data = r.get_json()
    assert data["agent_session_id"] == session_id
    assert len(data["messages"]) == 1
    assert data["messages"][0]["role"] == "assistant"
    assert "Sara" in data["messages"][0]["content"]


def test_post_message_simple_reply():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "msg@test.com", "password": "securepass1"})
    session_id = _create_agent(client)
    thread = client.post("/api/chat/threads", json={"agent_session_id": session_id}).get_json()

    r = client.post(f"/api/chat/threads/{thread['id']}/messages", json={
        "content": "What does churn mean?",
    })
    assert r.status_code == 202
    body = r.get_json()
    assert body["accepted"] is True
    assert body["user_message"]["role"] == "user"

    loaded = _wait_thread_done(client, thread["id"])
    assistant_msgs = [m for m in loaded["messages"] if m["role"] == "assistant" and not (m.get("meta") or {}).get("type") == "welcome"]
    assert assistant_msgs
    assert assistant_msgs[-1]["content"]
    assert assistant_msgs[-1]["meta"].get("mode") in ("simple", "direct")


def test_message_rating_toggle():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "rating@test.com", "password": "securepass1"})
    session_id = _create_agent(client)
    thread = client.post("/api/chat/threads", json={"agent_session_id": session_id}).get_json()

    client.post(f"/api/chat/threads/{thread['id']}/messages", json={
        "content": "What does churn mean?",
    })
    loaded = _wait_thread_done(client, thread["id"])
    assistant = next(
        m for m in reversed(loaded["messages"])
        if m["role"] == "assistant" and (m.get("meta") or {}).get("type") != "welcome"
    )

    up = client.post(f"/api/chat/messages/{assistant['id']}/rating", json={"rating": "up"})
    assert up.status_code == 200
    assert up.get_json()["rating"] == "up"
    assert up.get_json()["message"]["meta"]["rating"] == "up"

    toggle_off = client.post(f"/api/chat/messages/{assistant['id']}/rating", json={"rating": "up"})
    assert toggle_off.status_code == 200
    assert toggle_off.get_json()["rating"] is None

    down = client.post(f"/api/chat/messages/{assistant['id']}/rating", json={"rating": "down"})
    assert down.status_code == 200
    assert down.get_json()["rating"] == "down"

    user_msg = next(m for m in loaded["messages"] if m["role"] == "user")
    bad = client.post(f"/api/chat/messages/{user_msg['id']}/rating", json={"rating": "up"})
    assert bad.status_code == 400


def test_post_message_team_task():
    from tests.test_chat_orchestrator import PLAN_CONFIRMATION_PROMPT, _four_skill_framework

    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "team@test.com", "password": "securepass1"})
    client.post("/api/profile/background", json={
        "full_name": "Sara",
        "field": "Finance",
        "skillset": "FP&A, SQL, forecasting",
        "current_job": "Financial Analyst",
        "industry": "SaaS",
    })
    jd = {
        "title": "Analyst — Sara",
        "summary": "Finance agent.",
        "responsibilities": ["Build forecasts", "Analyze funnel data", "Prepare reports"],
    }
    session_id = client.post("/api/agents/create", json={
        "full_name": "Sara",
        "field": "Finance",
        "skillset": "FP&A, SQL, forecasting",
        "current_job": "Financial Analyst",
        "industry": "SaaS",
        "job_description": jd,
        "framework_design": {"framework": _four_skill_framework(), "construction_answers": {}},
    }).get_json()["session_id"]
    thread = client.post("/api/chat/threads", json={"agent_session_id": session_id}).get_json()

    r = client.post(f"/api/chat/threads/{thread['id']}/messages", json={
        "content": PLAN_CONFIRMATION_PROMPT,
    })
    assert r.status_code == 202

    loaded = _wait_thread_done(client, thread["id"])
    assistant_msgs = [m for m in loaded["messages"] if m["role"] == "assistant" and not (m.get("meta") or {}).get("type") == "welcome"]
    meta = assistant_msgs[-1]["meta"]
    assert meta.get("type") == "plan_proposal"
    assert loaded.get("pending_plan")
    assert meta.get("progress_card")
    assert meta["progress_card"]["total"] >= 2


def test_user_message_persisted_before_assistant_reply():
    from unittest.mock import patch

    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "persist@test.com", "password": "securepass1"})
    session_id = _create_agent(client)
    thread = client.post("/api/chat/threads", json={"agent_session_id": session_id}).get_json()

    seen_user = {"ok": False}

    def _turn(*args, **kwargs):
        from backend.models import ChatMessage

        msgs = ChatMessage.query.filter_by(thread_id=thread["id"], role="user").all()
        seen_user["ok"] = len(msgs) == 1
        return {"content": "Reply text", "meta": {"mode": "simple"}}

    with patch("backend.services.chat_generation.run_agent_turn", side_effect=_turn):
        r = client.post(f"/api/chat/threads/{thread['id']}/messages", json={
            "content": "Hello there",
        })

    assert r.status_code == 202
    loaded = _wait_thread_done(client, thread["id"])
    assert seen_user["ok"] is True
    assert loaded["is_generating"] is False
    roles = [m["role"] for m in loaded["messages"]]
    assert "user" in roles
    assert roles.count("assistant") >= 2


def test_cancel_generation_sets_flag():
    from backend.models import ChatThread, db

    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "cancel@test.com", "password": "securepass1"})
    session_id = _create_agent(client)
    thread = client.post("/api/chat/threads", json={"agent_session_id": session_id}).get_json()

    with app.app_context():
        row = db.session.get(ChatThread, thread["id"])
        row.is_generating = True
        row.generation_progress = {"phase_label": "Thinking…"}
        db.session.commit()

    r = client.post(f"/api/chat/threads/{thread['id']}/cancel")
    assert r.status_code == 200
    assert r.get_json().get("stopped") is True

    with app.app_context():
        row = db.session.get(ChatThread, thread["id"])
        assert row.is_generating is False


def test_thread_includes_generation_progress():
    from backend.models import ChatThread, db

    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "prog@test.com", "password": "securepass1"})
    session_id = _create_agent(client)
    thread = client.post("/api/chat/threads", json={"agent_session_id": session_id}).get_json()

    with app.app_context():
        row = db.session.get(ChatThread, thread["id"])
        row.is_generating = True
        row.generation_progress = {
            "mode": "team_task",
            "phase_label": "Delegating…",
            "steps": [{"label": "SQL Query", "status": "active"}],
        }
        db.session.commit()

    loaded = client.get(f"/api/chat/threads/{thread['id']}").get_json()
    assert loaded["generation_progress"]["mode"] == "team_task"
    assert loaded["generation_progress"]["steps"][0]["status"] == "active"


def test_thread_reports_generating_flag():
    from backend.models import ChatThread, db

    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "gen@test.com", "password": "securepass1"})
    session_id = _create_agent(client)
    thread = client.post("/api/chat/threads", json={"agent_session_id": session_id}).get_json()

    with app.app_context():
        row = db.session.get(ChatThread, thread["id"])
        row.is_generating = True
        db.session.commit()

    loaded = client.get(f"/api/chat/threads/{thread['id']}").get_json()
    assert loaded["is_generating"] is True


def test_history_excludes_cancelled_assistant_messages():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "hist@test.com", "password": "securepass1"})
    session_id = _create_agent(client)
    thread = client.post("/api/chat/threads", json={"agent_session_id": session_id}).get_json()

    with app.app_context():
        from backend.models import ChatMessage, ChatThread, db

        row = db.session.get(ChatThread, thread["id"])
        row.is_generating = True
        db.session.add(ChatMessage(
            thread_id=row.id,
            role="assistant",
            content="Generation stopped.",
            meta={"cancelled": True},
        ))
        db.session.add(ChatMessage(
            thread_id=row.id,
            role="user",
            content="Follow up question",
        ))
        db.session.commit()

    from backend.routes.chat import _history_for_thread

    with app.app_context():
        history = _history_for_thread(thread["id"])
        roles = [m["role"] for m in history]
        assert "user" in roles
        assert all("stopped" not in m["content"].lower() for m in history)


def test_delete_thread():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "delthread@test.com", "password": "securepass1"})
    session_id = _create_agent(client)
    thread = client.post("/api/chat/threads", json={"agent_session_id": session_id}).get_json()

    r = client.delete(f"/api/chat/threads/{thread['id']}")
    assert r.status_code == 200

    assert client.get(f"/api/chat/threads/{thread['id']}").status_code == 404

    sidebar = client.get("/api/chat/sidebar").get_json()
    assert not any(a["session_id"] == session_id for a in sidebar["agent_dms"])


def test_export_thread_markdown():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "export@test.com", "password": "securepass1"})
    session_id = _create_agent(client)
    thread = client.post("/api/chat/threads", json={"agent_session_id": session_id}).get_json()

    client.post(f"/api/chat/threads/{thread['id']}/messages", json={"content": "Hello"})

    r = client.get(f"/api/chat/threads/{thread['id']}/export?format=markdown")
    assert r.status_code == 200
    assert b"Hello" in r.data or b"hello" in r.data.lower()
    assert "attachment" in r.headers.get("Content-Disposition", "")


def test_delete_agent_cascades_threads():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "del@test.com", "password": "securepass1"})
    session_id = _create_agent(client)
    thread = client.post("/api/chat/threads", json={"agent_session_id": session_id}).get_json()

    r = client.delete(f"/api/agents/{session_id}")
    assert r.status_code == 200

    r2 = client.get(f"/api/chat/threads/{thread['id']}")
    assert r2.status_code == 404
