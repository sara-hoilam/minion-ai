"""Background jobs for conversation memory (compaction off the reply hot path)."""

from __future__ import annotations

import logging
import threading

from flask import Flask

logger = logging.getLogger(__name__)

_active_compactions: set[int] = set()
_guard = threading.Lock()


def schedule_thread_compaction(
    app: Flask,
    thread_id: int,
    user_id: int,
    agent_name: str,
    *,
    agent_session_id: int | None = None,
) -> bool:
    """
    Run maybe_compact_thread in a daemon thread so the chat reply returns immediately.
    Returns False if compaction for this thread is already running.
    """
    with _guard:
        if thread_id in _active_compactions:
            return False
        _active_compactions.add(thread_id)

    def _worker() -> None:
        try:
            with app.app_context():
                from backend.services.conversation_memory import maybe_compact_thread
                from backend.services.llm_usage_context import LlmUsageContext, llm_usage_scope

                usage_ctx = LlmUsageContext(
                    user_id=user_id,
                    thread_id=thread_id,
                    session_id=agent_session_id,
                    source="memory",
                )
                with llm_usage_scope(usage_ctx):
                    maybe_compact_thread(
                        thread_id,
                        user_id,
                        agent_name,
                        agent_session_id=agent_session_id,
                    )
        except Exception:
            logger.exception("Background memory compaction failed for thread %s", thread_id)
        finally:
            with _guard:
                _active_compactions.discard(thread_id)

    worker = threading.Thread(
        target=_worker,
        daemon=True,
        name=f"memory-compact-{thread_id}",
    )
    worker.start()
    return True


def is_compaction_running(thread_id: int) -> bool:
    with _guard:
        return thread_id in _active_compactions
