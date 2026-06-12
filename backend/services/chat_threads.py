"""Helpers for agent DM chat threads."""

from __future__ import annotations

from backend.models import ChatMessage, ChatThread, StudioSession, db
from backend.services.agent_builder import build_agent_framework
from backend.services.chat_orchestrator import welcome_message


def ensure_agent_dm_thread(user_id: int, session: StudioSession) -> ChatThread:
    """Create (or return) the direct-message thread for an agent."""
    existing = ChatThread.query.filter_by(
        user_id=user_id,
        agent_session_id=session.id,
        thread_type="agent_dm",
    ).first()
    if existing:
        return existing

    ctx = session.agent_context or {}
    framework = build_agent_framework(ctx)
    thread = ChatThread(
        user_id=user_id,
        thread_type="agent_dm",
        agent_session_id=session.id,
        title=f"Chat with {ctx.get('full_name', 'Agent')}",
    )
    db.session.add(thread)
    db.session.flush()

    db.session.add(ChatMessage(
        thread_id=thread.id,
        role="assistant",
        content=welcome_message(ctx, framework),
        meta={"type": "welcome", "agent_name": ctx.get("full_name")},
    ))
    return thread
