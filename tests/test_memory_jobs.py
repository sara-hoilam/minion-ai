"""Background memory compaction jobs."""

import time

from backend.app import create_app
from backend.models import ChatMessage, ChatThread, User, db
from backend.services.memory_jobs import is_compaction_running, schedule_thread_compaction


def test_schedule_compaction_runs_in_background(monkeypatch):
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": True,
    })
    started = []
    finished = []

    def slow_compact(*args, **kwargs):
        started.append(True)
        time.sleep(0.15)
        finished.append(True)
        return False

    monkeypatch.setattr(
        "backend.services.conversation_memory.maybe_compact_thread",
        slow_compact,
    )

    with app.app_context():
        db.create_all()
        user = User(email="job@test.com")
        user.set_password("password12")
        db.session.add(user)
        db.session.flush()
        thread = ChatThread(user_id=user.id, thread_type="agent_dm")
        db.session.add(thread)
        db.session.commit()
        thread_id = thread.id
        user_id = user.id

    t0 = time.time()
    with app.app_context():
        assert schedule_thread_compaction(app, thread_id, user_id, "Sara") is True
        assert schedule_thread_compaction(app, thread_id, user_id, "Sara") is False
    elapsed = time.time() - t0
    assert elapsed < 0.1
    assert is_compaction_running(thread_id)

    deadline = time.time() + 2.0
    while time.time() < deadline and not finished:
        time.sleep(0.05)
    assert finished
    assert not is_compaction_running(thread_id)


def test_thread_memory_api():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "memapi@test.com", "password": "securepass1"})

    with app.app_context():
        from backend.models import ThreadTopic

        user = User.query.filter_by(email="memapi@test.com").first()
        thread = ChatThread(user_id=user.id, thread_type="agent_dm")
        db.session.add(thread)
        db.session.flush()
        db.session.add(ChatMessage(thread_id=thread.id, role="user", content="Hello"))
        db.session.add(ThreadTopic(
            thread_id=thread.id,
            title="Onboarding",
            summary="Discussed onboarding metrics.",
            key_insights=["Focus on week-1 activation"],
            status="active",
        ))
        db.session.commit()
        thread_id = thread.id

    r = client.get(f"/api/chat/threads/{thread_id}/memory")
    assert r.status_code == 200
    data = r.get_json()
    assert data["topics"][0]["title"] == "Onboarding"
    assert data["eligible_message_count"] == 1
