"""Background chat generation and fast cancellation."""



from __future__ import annotations



import logging

import threading

from datetime import datetime, timezone



from flask import Flask



from backend.models import AgentArtifact, ChatMessage, ChatThread, StudioSession, db

from backend.services.agent_builder import build_agent_framework

from backend.services.chat_orchestrator import (
    _is_direct_answer,
    _should_use_team_mode,
    _skill_agents,
    run_agent_turn,
)

from backend.services.chat_progress import (
    ChatGenerationCancelled,
    ChatProgressReporter,
    thought_meta_from_progress,
)

from backend.services.conversation_memory import build_memory_context
from backend.services.memory_jobs import schedule_thread_compaction

from backend.services.cursor_llm import cancel_run as cursor_cancel_run

from backend.services.event_logger import log_event



logger = logging.getLogger(__name__)





def _owned_thread(thread_id: int) -> ChatThread | None:

    return ChatThread.query.filter_by(id=thread_id).first()





def _last_assistant_cancelled(thread_id: int) -> bool:

    last = (

        ChatMessage.query.filter_by(thread_id=thread_id, role="assistant")

        .order_by(ChatMessage.created_at.desc())

        .first()

    )

    return bool(last and (last.meta or {}).get("cancelled"))





def _generation_is_current(thread: ChatThread | None, generation_seq: int) -> bool:

    return bool(

        thread

        and thread.is_generating

        and thread.generation_seq == generation_seq

    )





def finalize_cancel(thread_id: int, agent_name: str) -> None:

    """Stop only the active run; keep cloud agent id and chat history intact."""

    thread = _owned_thread(thread_id)

    if not thread:

        return



    run_info = thread.active_cursor_run or {}

    agent_id = run_info.get("agent_id")

    run_id = run_info.get("run_id")

    if agent_id and run_id:

        try:

            cursor_cancel_run(agent_id, run_id)

        except Exception as exc:

            logger.warning("Cursor cancel failed for thread %s: %s", thread_id, exc)



    thread.cancel_requested = True

    thread.is_generating = False

    thread.generation_progress = None

    thread.active_cursor_run = None

    thread.cancel_requested = False

    thread.updated_at = datetime.now(timezone.utc)



    if not _last_assistant_cancelled(thread_id):

        db.session.add(ChatMessage(

            thread_id=thread.id,

            role="assistant",

            content="Generation stopped.",

            meta={"agent_name": agent_name, "cancelled": True},

        ))



    db.session.commit()





def _save_success(

    thread_id: int,

    user_id: int,

    session_id: int,

    agent_name: str,

    result: dict,

    generation_seq: int,

) -> None:

    thread = _owned_thread(thread_id)

    if not _generation_is_current(thread, generation_seq):

        db.session.rollback()

        return



    assistant_meta = result.get("meta") or {}

    assistant_meta["agent_name"] = agent_name

    progress_snapshot = dict(thread.generation_progress or {})
    thought = thought_meta_from_progress(progress_snapshot)
    if thought:
        assistant_meta["thought"] = thought

    new_cloud_agent_id = assistant_meta.pop("cursor_cloud_agent_id", None)

    if new_cloud_agent_id:

        thread.cursor_cloud_agent_id = new_cloud_agent_id



    artifact_records = []

    for art in assistant_meta.get("artifacts") or []:

        record = AgentArtifact(

            user_id=user_id,

            session_id=session_id,

            artifact_type=art.get("artifact_type", "chat_deliverable_docx"),

            file_path=art.get("path"),

            content_preview=art.get("title", art.get("filename", ""))[:500],

        )

        db.session.add(record)

        db.session.flush()

        artifact_records.append({

            "id": record.id,

            "filename": art.get("filename"),

            "title": art.get("title"),

            "size_bytes": art.get("size_bytes"),

        })

    assistant_meta["artifacts"] = artifact_records



    db.session.add(ChatMessage(

        thread_id=thread.id,

        role="assistant",

        content=result["content"],

        meta=assistant_meta,

    ))

    thread.is_generating = False

    thread.cancel_requested = False

    thread.generation_progress = None

    thread.active_cursor_run = None

    thread.pending_plan = None

    thread.updated_at = datetime.now(timezone.utc)

    db.session.commit()



    log_event("chat_message_sent", {

        "thread_id": thread.id,

        "agent_session_id": session_id,

        "mode": assistant_meta.get("mode", "simple"),

    }, session_id=str(session_id))





def _save_plan_proposal(

    thread_id: int,

    session_id: int,

    agent_name: str,

    result: dict,

    *,

    content: str,

    combined_context: str,

    history: list[dict],

    generation_seq: int,

    user_feedback: str | None = None,

    revision_round: int = 0,

) -> None:

    thread = _owned_thread(thread_id)

    if not _generation_is_current(thread, generation_seq):

        db.session.rollback()

        return



    plan = result.get("plan") or (result.get("meta") or {}).get("plan") or {}

    thread.pending_plan = {

        "content": content,

        "combined_context": combined_context,

        "history": history,

        "plan": plan,

        "session_id": session_id,

        "revision_round": revision_round,

        "user_feedback": user_feedback,

    }

    progress_snapshot = dict(thread.generation_progress or {})

    thread.is_generating = False

    thread.cancel_requested = False

    thread.generation_progress = None

    thread.active_cursor_run = None

    thread.updated_at = datetime.now(timezone.utc)



    existing = (

        ChatMessage.query.filter_by(thread_id=thread_id, role="assistant")

        .order_by(ChatMessage.created_at.desc())

        .first()

    )

    meta = result.get("meta") or {}

    meta["agent_name"] = agent_name

    thought = thought_meta_from_progress(progress_snapshot)
    if thought:
        meta["thought"] = thought

    if existing and (existing.meta or {}).get("type") == "plan_proposal":

        existing.content = result["content"]

        existing.meta = meta

    else:

        db.session.add(ChatMessage(

            thread_id=thread_id,

            role="assistant",

            content=result["content"],

            meta=meta,

        ))



    db.session.commit()





def _save_error(thread_id: int, agent_name: str, exc: Exception, generation_seq: int) -> None:

    thread = _owned_thread(thread_id)

    if not _generation_is_current(thread, generation_seq):

        db.session.rollback()

        return



    db.session.add(ChatMessage(

        thread_id=thread.id,

        role="assistant",

        content=f"Sorry, something went wrong while generating a reply: {exc}",

        meta={"agent_name": agent_name, "error": True},

    ))

    thread.is_generating = False

    thread.cancel_requested = False

    thread.generation_progress = None

    thread.active_cursor_run = None

    thread.updated_at = datetime.now(timezone.utc)

    db.session.commit()





def _generation_worker(

    app: Flask,

    thread_id: int,

    user_id: int,

    session_id: int,

    content: str,

    history: list[dict],

    combined_context: str,

    cloud_agent_id: str | None,

    generation_seq: int,

    approved_plan: dict | None = None,

    user_feedback: str | None = None,

    revision_round: int = 0,

) -> None:

    with app.app_context():

        agent_name = "Agent"

        try:

            session = db.session.get(StudioSession, session_id)

            thread = _owned_thread(thread_id)

            if not session or not _generation_is_current(thread, generation_seq):

                return



            ctx = session.agent_context or {}

            agent_name = ctx.get("full_name") or "Agent"

            framework = build_agent_framework(ctx)

            reporter = ChatProgressReporter(thread_id, generation_seq)

            skill_agents = _skill_agents(framework)
            if _is_direct_answer(content):
                reporter.begin_simple(agent_name, content, routing="direct")
            elif len(skill_agents) >= 2 and _should_use_team_mode(content, skill_agents, framework):
                reporter.begin_planning(agent_name, content, skill_agents)

            memory_context = build_memory_context(thread_id, content)

            result = run_agent_turn(

                ctx,

                framework,

                content,

                history=history,

                file_context=combined_context,

                user_id=user_id,

                agent_session_id=session_id,

                cloud_agent_id=cloud_agent_id,

                progress=reporter,

                approved_plan=approved_plan,

                user_feedback=user_feedback,

                memory_context=memory_context,

            )



            if result.get("needs_confirmation"):

                _save_plan_proposal(

                    thread_id,

                    session_id,

                    agent_name,

                    result,

                    content=content,

                    combined_context=combined_context,

                    history=history,

                    generation_seq=generation_seq,

                    user_feedback=user_feedback,

                    revision_round=revision_round,

                )

                return



            _save_success(thread_id, user_id, session_id, agent_name, result, generation_seq)

            schedule_thread_compaction(

                app,

                thread_id,

                user_id,

                agent_name,

                agent_session_id=session_id,

            )

        except ChatGenerationCancelled:

            db.session.rollback()

            thread = _owned_thread(thread_id)

            if thread and thread.is_generating and thread.generation_seq == generation_seq:

                finalize_cancel(thread_id, agent_name)

        except Exception as exc:

            db.session.rollback()

            logger.exception("Background generation failed for thread %s", thread_id)

            session = db.session.get(StudioSession, session_id)

            if session:

                agent_name = (session.agent_context or {}).get("full_name") or "Agent"

            _save_error(thread_id, agent_name, exc, generation_seq)





def start_generation(

    app: Flask,

    thread_id: int,

    user_id: int,

    session_id: int,

    content: str,

    history: list[dict],

    combined_context: str,

    cloud_agent_id: str | None,

    generation_seq: int,

    approved_plan: dict | None = None,

    user_feedback: str | None = None,

    revision_round: int = 0,

) -> None:

    worker = threading.Thread(

        target=_generation_worker,

        args=(

            app,

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

        ),

        daemon=True,

        name=f"chat-gen-{thread_id}-{generation_seq}",

    )

    worker.start()


