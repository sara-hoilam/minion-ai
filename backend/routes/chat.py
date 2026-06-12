"""Chat workspace API — threads, messages, file context."""

import csv
import io
import re
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request, send_file, Response
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from backend.config import UPLOAD_FOLDER
from backend.models import AgentArtifact, ChatMessage, ChatThread, Project, StudioSession, db
from backend.services.agent_builder import build_agent_framework
from backend.services.chat_generation import finalize_cancel, start_generation
from backend.services.chat_orchestrator import _is_direct_answer
from backend.services.chat_orchestrator import welcome_message
from backend.services.chat_progress import ChatProgressReporter
from backend.services.cursor_llm import cancel_run as cursor_cancel_run
from backend.services.feedback_adaptation import format_feedback_digest
from backend.services.file_context import read_file_context_from_bytes
from backend.services.supabase_storage import download_project_file

chat_bp = Blueprint("chat", __name__, url_prefix="/api/chat")

CHAT_UPLOAD = UPLOAD_FOLDER / "chat"
ALLOWED_EXTENSIONS = {".csv", ".txt", ".md", ".pdf", ".docx", ".xlsx", ".xls"}


def _owned_agent_session(session_id: int) -> StudioSession | None:
    return StudioSession.query.filter_by(
        id=session_id,
        user_id=current_user.id,
    ).filter(StudioSession.agent_generated_at.isnot(None)).first()


def _owned_thread(thread_id: int) -> ChatThread | None:
    return ChatThread.query.filter_by(id=thread_id, user_id=current_user.id).first()


def _owned_message(message_id: int) -> ChatMessage | None:
    msg = db.session.get(ChatMessage, message_id)
    if not msg:
        return None
    if not _owned_thread(msg.thread_id):
        return None
    return msg


def _message_dict(msg: ChatMessage) -> dict:
    return {
        "id": msg.id,
        "role": msg.role,
        "content": msg.content,
        "meta": msg.meta or {},
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


def _agent_label(session_id: int | None) -> dict:
    if not session_id:
        return {"name": "Agent", "job_title": None}
    session = db.session.get(StudioSession, session_id)
    ctx = (session.agent_context or {}) if session else {}
    return {
        "name": ctx.get("full_name") or "Agent",
        "job_title": ctx.get("current_job"),
        "field": ctx.get("field"),
    }


def _thread_dict(thread: ChatThread, include_messages: bool = False) -> dict:
    label = _agent_label(thread.agent_session_id)
    participants = []
    for aid in thread.participant_agent_ids or []:
        info = _agent_label(aid)
        participants.append({"session_id": aid, **info})

    data = {
        "id": thread.id,
        "thread_type": thread.thread_type or "agent_dm",
        "agent_session_id": thread.agent_session_id,
        "agent_name": label["name"],
        "participant_agent_ids": thread.participant_agent_ids or [],
        "participants": participants,
        "project_id": thread.project_id,
        "title": thread.title,
        "pinned": thread.pinned,
        "is_generating": bool(thread.is_generating),
        "pending_plan": thread.pending_plan,
        "generation_progress": thread.generation_progress,
        "created_at": thread.created_at.isoformat() if thread.created_at else None,
        "updated_at": thread.updated_at.isoformat() if thread.updated_at else None,
    }
    if thread.project_id:
        project = db.session.get(Project, thread.project_id)
        if project:
            data["project_name"] = project.name
    if include_messages:
        messages = (
            ChatMessage.query.filter_by(thread_id=thread.id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )
        data["messages"] = [_message_dict(m) for m in messages]
    return data


def _project_context(project: Project) -> str:
    parts = [f"Project: {project.name}"]
    if project.description:
        parts.append(f"Description: {project.description}")
    if project.instructions:
        parts.append(f"Instructions:\n{project.instructions}")
    for f in project.context_files or []:
        storage_path = f.get("storage_path")
        filename = f.get("filename", "file")
        if storage_path:
            try:
                data = download_project_file(storage_path)
                parts.append(read_file_context_from_bytes(data, filename))
            except Exception as exc:
                parts.append(f"File {filename} (could not load: {exc})")
        else:
            path = Path(f.get("path", ""))
            if path.exists():
                parts.append(_read_file_context(path, filename))
    return "\n\n".join(parts)[:12000]


def _agent_working_context(session: StudioSession) -> str:
    ctx = session.agent_context or {}
    parts = []
    digest = format_feedback_digest(ctx)
    if digest:
        parts.append(digest)
    elif ctx.get("working_instructions"):
        parts.append(
            f"Standing instructions for {ctx.get('full_name', 'this agent')}:\n{ctx['working_instructions']}"
        )
    for f in ctx.get("context_files") or []:
        path = Path(f.get("path", ""))
        if path.exists():
            parts.append(_read_file_context(path, f.get("filename", path.name)))
    return "\n\n".join(parts)[:12000]


def _read_file_context(path: Path, original_name: str) -> str:
    ext = path.suffix.lower()
    try:
        if ext == ".csv":
            text = path.read_text(encoding="utf-8", errors="replace")
            reader = csv.reader(io.StringIO(text))
            rows = list(reader)[:50]
            preview = "\n".join(", ".join(row) for row in rows)
            return f"CSV file {original_name} (first {len(rows)} rows):\n{preview[:6000]}"
        if ext in (".txt", ".md"):
            return path.read_text(encoding="utf-8", errors="replace")[:8000]
        if ext == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            pages = []
            for page in reader.pages[:5]:
                pages.append(page.extract_text() or "")
            return f"PDF {original_name}:\n" + "\n".join(pages)[:8000]
        if ext == ".docx":
            from docx import Document

            doc = Document(str(path))
            paras = [p.text for p in doc.paragraphs if p.text.strip()][:40]
            return f"Document {original_name}:\n" + "\n".join(paras)[:8000]
    except Exception as e:
        return f"File {original_name} uploaded (could not parse: {e})"
    return f"File {original_name} attached."


def _history_for_thread(thread_id: int) -> list[dict]:
    from backend.services.conversation_memory import load_thread_messages, messages_to_history

    return messages_to_history(load_thread_messages(thread_id))


def _start_thread_generation(
    thread: ChatThread,
    session_id: int,
    content: str,
    history: list[dict],
    combined_context: str,
    agent_name: str,
    *,
    approved_plan: dict | None = None,
    user_feedback: str | None = None,
    revision_round: int = 0,
) -> int:
    thread.is_generating = True
    thread.cancel_requested = False
    thread.generation_seq = (thread.generation_seq or 0) + 1
    generation_seq = thread.generation_seq
    thread.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    reporter = ChatProgressReporter(thread.id, generation_seq)
    if _is_direct_answer(content):
        reporter.begin_simple(agent_name, content, routing="direct")
    else:
        reporter.begin_starting(agent_name)
    progress_snapshot = reporter.snapshot()

    start_generation(
        current_app._get_current_object(),
        thread.id,
        current_user.id,
        session_id,
        content,
        history,
        combined_context,
        thread.cursor_cloud_agent_id,
        generation_seq,
        approved_plan=approved_plan,
        user_feedback=user_feedback,
        revision_round=revision_round,
    )
    return generation_seq, progress_snapshot


@chat_bp.route("/agents", methods=["GET"])
@login_required
def list_chat_agents():
    sessions = (
        StudioSession.query.filter_by(user_id=current_user.id)
        .filter(StudioSession.agent_generated_at.isnot(None))
        .order_by(StudioSession.agent_generated_at.desc())
        .all()
    )
    agents = []
    for s in sessions:
        ctx = s.agent_context or {}
        agents.append({
            "session_id": s.id,
            "name": ctx.get("full_name") or "Agent",
            "job_title": ctx.get("current_job"),
            "field": ctx.get("field"),
            "industry": ctx.get("industry"),
        })
    return jsonify({"agents": agents})


@chat_bp.route("/sidebar", methods=["GET"])
@login_required
def sidebar():
    """Slack-style sidebar: agent DMs, group chats."""
    agents_raw = (
        StudioSession.query.filter_by(user_id=current_user.id)
        .filter(StudioSession.agent_generated_at.isnot(None))
        .order_by(StudioSession.agent_generated_at.desc())
        .all()
    )
    agent_dms = []
    for s in agents_raw:
        ctx = s.agent_context or {}
        thread = (
            ChatThread.query.filter_by(
                user_id=current_user.id,
                agent_session_id=s.id,
                thread_type="agent_dm",
            )
            .order_by(ChatThread.updated_at.desc())
            .first()
        )
        agent_dms.append({
            "session_id": s.id,
            "name": ctx.get("full_name") or "Agent",
            "job_title": ctx.get("current_job"),
            "field": ctx.get("field"),
            "thread_id": thread.id if thread else None,
            "updated_at": thread.updated_at.isoformat() if thread and thread.updated_at else None,
            "hidden_from_roster": bool(ctx.get("hidden_from_roster")),
        })

    groups = (
        ChatThread.query.filter_by(user_id=current_user.id, thread_type="group")
        .order_by(ChatThread.updated_at.desc())
        .all()
    )
    return jsonify({
        "agent_dms": agent_dms,
        "group_chats": [_thread_dict(t) for t in groups],
    })


@chat_bp.route("/threads", methods=["GET"])
@login_required
def list_threads():
    agent_session_id = request.args.get("agent_session_id", type=int)
    thread_type = request.args.get("thread_type")
    project_id = request.args.get("project_id", type=int)
    q = ChatThread.query.filter_by(user_id=current_user.id)
    if agent_session_id:
        q = q.filter_by(agent_session_id=agent_session_id)
    if thread_type:
        q = q.filter_by(thread_type=thread_type)
    if project_id:
        q = q.filter_by(project_id=project_id)
    threads = q.order_by(ChatThread.updated_at.desc()).limit(50).all()
    return jsonify({"threads": [_thread_dict(t) for t in threads]})


@chat_bp.route("/threads", methods=["POST"])
@login_required
def create_thread():
    data = request.get_json() or {}
    thread_type = data.get("thread_type", "agent_dm")

    if thread_type == "group":
        participant_ids = []
        for aid in data.get("participant_agent_ids") or []:
            if _owned_agent_session(int(aid)):
                participant_ids.append(int(aid))
        if len(participant_ids) < 2:
            return jsonify({"error": "Select at least 2 agents for a group chat"}), 400

        names = [_agent_label(aid)["name"] for aid in participant_ids]
        title = data.get("title") or ", ".join(names[:3])
        if len(names) > 3:
            title += f" +{len(names) - 3}"

        thread = ChatThread(
            user_id=current_user.id,
            thread_type="group",
            agent_session_id=participant_ids[0],
            participant_agent_ids=participant_ids,
            title=title,
        )
        db.session.add(thread)
        db.session.flush()
        db.session.add(ChatMessage(
            thread_id=thread.id,
            role="assistant",
            content=(
                f"Group chat with **{', '.join(names)}**.\n\n"
                "Mention an agent with @Name to direct your message. "
                "Everyone on this thread can collaborate on your request."
            ),
            meta={"type": "welcome", "participants": names},
        ))
        db.session.commit()
        return jsonify(_thread_dict(thread, include_messages=True)), 201

    if thread_type == "project_agent":
        project_id = data.get("project_id")
        agent_session_id = data.get("agent_session_id")
        if not project_id or not agent_session_id:
            return jsonify({"error": "project_id and agent_session_id are required"}), 400

        project = Project.query.filter_by(id=int(project_id), user_id=current_user.id).first()
        if not project:
            return jsonify({"error": "Project not found"}), 404
        if int(agent_session_id) not in (project.agent_session_ids or []):
            return jsonify({"error": "Agent is not assigned to this project"}), 400

        session = _owned_agent_session(int(agent_session_id))
        if not session:
            return jsonify({"error": "Agent not found"}), 404

        existing = ChatThread.query.filter_by(
            user_id=current_user.id,
            project_id=project.id,
            agent_session_id=int(agent_session_id),
            thread_type="project_agent",
        ).first()
        if existing:
            return jsonify(_thread_dict(existing, include_messages=True)), 200

        label = _agent_label(int(agent_session_id))
        thread = ChatThread(
            user_id=current_user.id,
            thread_type="project_agent",
            project_id=project.id,
            agent_session_id=int(agent_session_id),
            title=f"{project.name} · {label['name']}",
        )
        db.session.add(thread)
        db.session.flush()

        ctx = session.agent_context or {}
        framework = build_agent_framework(ctx)
        intro = f"**Project: {project.name}**\n\n"
        if project.description:
            intro += f"{project.description}\n\n"
        if project.instructions:
            intro += f"**Instructions:**\n{project.instructions}\n\n"
        intro += welcome_message(ctx, framework)
        db.session.add(ChatMessage(
            thread_id=thread.id,
            role="assistant",
            content=intro,
            meta={"type": "welcome", "project_id": project.id, "agent_name": label["name"]},
        ))
        db.session.commit()
        return jsonify(_thread_dict(thread, include_messages=True)), 201

    agent_session_id = data.get("agent_session_id")
    if not agent_session_id:
        return jsonify({"error": "agent_session_id is required"}), 400

    session = _owned_agent_session(agent_session_id)
    if not session:
        return jsonify({"error": "Agent not found"}), 404

    existing = ChatThread.query.filter_by(
        user_id=current_user.id,
        agent_session_id=agent_session_id,
        thread_type="agent_dm",
    ).first()
    if existing:
        return jsonify(_thread_dict(existing, include_messages=True)), 200

    ctx = session.agent_context or {}
    framework = build_agent_framework(ctx)
    title = data.get("title") or f"Chat with {ctx.get('full_name', 'Agent')}"

    thread = ChatThread(
        user_id=current_user.id,
        thread_type="agent_dm",
        agent_session_id=agent_session_id,
        title=title,
    )
    db.session.add(thread)
    db.session.flush()

    welcome = welcome_message(ctx, framework)
    db.session.add(ChatMessage(
        thread_id=thread.id,
        role="assistant",
        content=welcome,
        meta={"type": "welcome", "agent_name": ctx.get("full_name")},
    ))
    db.session.commit()

    return jsonify(_thread_dict(thread, include_messages=True)), 201


@chat_bp.route("/threads/<int:thread_id>/memory", methods=["GET"])
@login_required
def get_thread_memory(thread_id: int):
    thread = _owned_thread(thread_id)
    if not thread:
        return jsonify({"error": "Thread not found"}), 404
    from backend.services.conversation_memory import get_thread_memory_snapshot

    return jsonify(get_thread_memory_snapshot(thread_id))


@chat_bp.route("/threads/<int:thread_id>", methods=["GET"])
@login_required
def get_thread(thread_id: int):
    thread = _owned_thread(thread_id)
    if not thread:
        return jsonify({"error": "Thread not found"}), 404
    return jsonify(_thread_dict(thread, include_messages=True))


def _thread_export_markdown(thread: ChatThread, messages: list[ChatMessage]) -> str:
    label = _agent_label(thread.agent_session_id)
    title = thread.title or f"Chat with {label['name']}"
    lines = [f"# {title}", ""]
    if thread.thread_type == "group":
        lines.append("*Group chat*")
        lines.append("")
    for msg in messages:
        role = msg.role
        if role not in ("user", "assistant"):
            continue
        name = "You" if role == "user" else (msg.meta or {}).get("agent_name") or label["name"]
        ts = msg.created_at.strftime("%Y-%m-%d %H:%M") if msg.created_at else ""
        header = f"## {name}" + (f" · {ts}" if ts else "")
        lines.extend([header, "", msg.content.strip(), ""])
    return "\n".join(lines).strip() + "\n"


def _safe_export_filename(name: str, ext: str) -> str:
    safe = re.sub(r"[^\w\s-]", "", name or "chat").strip().replace(" ", "_")[:40] or "chat"
    return f"{safe}.{ext}"


@chat_bp.route("/threads/<int:thread_id>/export", methods=["GET"])
@login_required
def export_thread(thread_id: int):
    thread = _owned_thread(thread_id)
    if not thread:
        return jsonify({"error": "Thread not found"}), 404

    messages = (
        ChatMessage.query.filter_by(thread_id=thread.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    fmt = (request.args.get("format") or "markdown").lower()
    label = thread.title or _agent_label(thread.agent_session_id)["name"]

    if fmt == "json":
        return jsonify({
            "thread": _thread_dict(thread),
            "messages": [_message_dict(m) for m in messages],
        })

    body = _thread_export_markdown(thread, messages)
    filename = _safe_export_filename(label, "md")
    return Response(
        body,
        mimetype="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@chat_bp.route("/threads/<int:thread_id>", methods=["DELETE"])
@login_required
def delete_thread(thread_id: int):
    thread = _owned_thread(thread_id)
    if not thread:
        return jsonify({"error": "Thread not found"}), 404

    run_info = thread.active_cursor_run or {}
    agent_id = run_info.get("agent_id")
    run_id = run_info.get("run_id")
    if agent_id and run_id:
        try:
            cursor_cancel_run(agent_id, run_id)
        except Exception:
            pass

    db.session.delete(thread)
    db.session.commit()
    return jsonify({"ok": True, "thread_id": thread_id})


@chat_bp.route("/threads/<int:thread_id>/cancel", methods=["POST"])
@login_required
def cancel_thread_generation(thread_id: int):
    thread = _owned_thread(thread_id)
    if not thread:
        return jsonify({"error": "Thread not found"}), 404
    if not thread.is_generating:
        return jsonify({"error": "Nothing in progress to stop"}), 400

    agent_name = _agent_label(thread.agent_session_id)["name"]
    finalize_cancel(thread_id, agent_name)

    return jsonify({"ok": True, "thread_id": thread_id, "stopped": True})


@chat_bp.route("/threads/<int:thread_id>/messages", methods=["POST"])
@login_required
def post_message(thread_id: int):
    thread = _owned_thread(thread_id)
    if not thread:
        return jsonify({"error": "Thread not found"}), 404

    project_context = ""
    if thread.project_id:
        project = db.session.get(Project, thread.project_id)
        if project:
            project_context = _project_context(project)

    session = _owned_agent_session(thread.agent_session_id) if thread.agent_session_id else None
    if not session and thread.thread_type in ("project", "project_agent") and thread.project_id:
        project = db.session.get(Project, thread.project_id)
        if project and project.agent_session_ids:
            session = _owned_agent_session(project.agent_session_ids[0])
            thread.agent_session_id = project.agent_session_ids[0]
    if not session:
        return jsonify({"error": "No agent assigned to this conversation"}), 400

    content = ""
    file_context = ""
    uploaded_meta = None

    if request.content_type and "multipart/form-data" in request.content_type:
        content = (request.form.get("content") or "").strip()
        upload = request.files.get("file")
        if upload and upload.filename:
            ext = Path(upload.filename).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                return jsonify({"error": f"Unsupported file type: {ext}"}), 400
            CHAT_UPLOAD.mkdir(parents=True, exist_ok=True)
            safe = secure_filename(upload.filename)
            dest = CHAT_UPLOAD / f"{current_user.id}_{thread_id}_{safe}"
            upload.save(dest)
            file_context = _read_file_context(dest, upload.filename)
            uploaded_meta = {"filename": upload.filename, "path": str(dest)}
    else:
        data = request.get_json() or {}
        content = (data.get("content") or "").strip()
        target_agent_id = data.get("agent_session_id")
        if target_agent_id:
            other = _owned_agent_session(int(target_agent_id))
            if other:
                thread.agent_session_id = int(target_agent_id)
                session = other

    if thread.thread_type == "group" and content:
        for aid in thread.participant_agent_ids or []:
            label = _agent_label(aid)
            if f"@{label['name']}" in content:
                other = _owned_agent_session(aid)
                if other:
                    session = other
                    thread.agent_session_id = aid
                    break

    if not content and not file_context:
        return jsonify({"error": "Message content or file is required"}), 400

    if thread.is_generating:
        return jsonify({"error": "Agent is still responding. Please wait."}), 409

    if thread.pending_plan:
        return jsonify({
            "error": "A workflow plan is awaiting your confirmation. Approve, revise, or dismiss it first.",
        }), 409

    from backend.services.subscription_service import ensure_token_budget

    allowed, budget_err = ensure_token_budget(current_user, 0.01)
    if not allowed:
        return jsonify({"error": budget_err, "code": "subscription_required"}), 402

    if not content and file_context:
        content = f"[Uploaded file: {uploaded_meta['filename']}]"

    ctx = session.agent_context or {}
    agent_name = ctx.get("full_name") or "Agent"

    agent_context_str = _agent_working_context(session)
    combined_context = "\n\n".join(filter(None, [agent_context_str, project_context, file_context]))

    display_content = content
    if content and not content.startswith("@") and thread.thread_type != "group":
        display_content = f"@{agent_name} {content}"

    history = _history_for_thread(thread.id)

    user_msg = ChatMessage(
        thread_id=thread.id,
        role="user",
        content=display_content,
        meta={"file": uploaded_meta} if uploaded_meta else None,
    )
    db.session.add(user_msg)
    db.session.commit()

    _generation_seq, progress_snapshot = _start_thread_generation(
        thread,
        session.id,
        content,
        history,
        combined_context,
        agent_name,
    )

    return jsonify({
        "accepted": True,
        "user_message": _message_dict(user_msg),
        "generation_progress": progress_snapshot,
    }), 202


@chat_bp.route("/threads/<int:thread_id>/plan/confirm", methods=["POST"])
@login_required
def confirm_thread_plan(thread_id: int):
    thread = _owned_thread(thread_id)
    if not thread:
        return jsonify({"error": "Thread not found"}), 404
    if not thread.pending_plan:
        return jsonify({"error": "No plan awaiting confirmation"}), 404
    if thread.is_generating:
        return jsonify({"error": "Agent is still responding. Please wait."}), 409

    from backend.services.subscription_service import ensure_token_budget

    allowed, budget_err = ensure_token_budget(current_user, 0.01)
    if not allowed:
        return jsonify({"error": budget_err, "code": "subscription_required"}), 402

    pending = dict(thread.pending_plan)
    session_id = pending.get("session_id") or thread.agent_session_id
    session = _owned_agent_session(session_id) if session_id else None
    if not session:
        return jsonify({"error": "Agent session not found"}), 400

    agent_name = (session.agent_context or {}).get("full_name") or "Agent"
    plan = pending.get("plan") or {}
    if not plan.get("subtasks"):
        return jsonify({"error": "Stored plan is invalid"}), 400

    thread.pending_plan = None
    thread.updated_at = datetime.now(timezone.utc)

    last = (
        ChatMessage.query.filter_by(thread_id=thread_id, role="assistant")
        .order_by(ChatMessage.created_at.desc())
        .first()
    )
    if last and (last.meta or {}).get("type") == "plan_proposal":
        meta = dict(last.meta or {})
        meta["confirmed"] = True
        progress_card = dict(meta.get("progress_card") or {})
        progress_card["status"] = "confirmed"
        progress_card["summary"] = "Confirmed to run"
        meta["progress_card"] = progress_card
        last.meta = meta

    db.session.commit()

    _generation_seq, progress_snapshot = _start_thread_generation(
        thread,
        session.id,
        pending.get("content") or "",
        pending.get("history") or [],
        pending.get("combined_context") or "",
        agent_name,
        approved_plan=plan,
    )

    return jsonify({
        "accepted": True,
        "executing": True,
        "thread_id": thread_id,
        "generation_progress": progress_snapshot,
    }), 202


@chat_bp.route("/threads/<int:thread_id>/plan/revise", methods=["POST"])
@login_required
def revise_thread_plan(thread_id: int):
    thread = _owned_thread(thread_id)
    if not thread:
        return jsonify({"error": "Thread not found"}), 404
    if not thread.pending_plan:
        return jsonify({"error": "No plan awaiting confirmation"}), 404
    if thread.is_generating:
        return jsonify({"error": "Agent is still responding. Please wait."}), 409

    comments = (request.get_json() or {}).get("comments") or ""
    comments = comments.strip()
    if not comments:
        return jsonify({"error": "Revision comments are required"}), 400

    pending = dict(thread.pending_plan)
    session_id = pending.get("session_id") or thread.agent_session_id
    session = _owned_agent_session(session_id) if session_id else None
    if not session:
        return jsonify({"error": "Agent session not found"}), 400

    agent_name = (session.agent_context or {}).get("full_name") or "Agent"
    revision_round = int(pending.get("revision_round") or 0) + 1

    _generation_seq, _progress_snapshot = _start_thread_generation(
        thread,
        session.id,
        pending.get("content") or "",
        pending.get("history") or [],
        pending.get("combined_context") or "",
        agent_name,
        user_feedback=comments,
        revision_round=revision_round,
    )

    return jsonify({"accepted": True, "revising": True, "thread_id": thread_id}), 202


@chat_bp.route("/threads/<int:thread_id>/plan/dismiss", methods=["POST"])
@login_required
def dismiss_thread_plan(thread_id: int):
    thread = _owned_thread(thread_id)
    if not thread:
        return jsonify({"error": "Thread not found"}), 404
    if not thread.pending_plan:
        return jsonify({"error": "No plan awaiting confirmation"}), 404
    if thread.is_generating:
        return jsonify({"error": "Agent is still responding. Please wait."}), 409

    agent_name = _agent_label(thread.agent_session_id)["name"]
    thread.pending_plan = None
    thread.updated_at = datetime.now(timezone.utc)

    last = (
        ChatMessage.query.filter_by(thread_id=thread_id, role="assistant")
        .order_by(ChatMessage.created_at.desc())
        .first()
    )
    if last and (last.meta or {}).get("type") == "plan_proposal":
        meta = dict(last.meta or {})
        meta["dismissed"] = True
        last.meta = meta

    db.session.commit()
    return jsonify({"ok": True, "thread_id": thread_id, "agent_name": agent_name})


@chat_bp.route("/messages/<int:message_id>/rating", methods=["POST"])
@login_required
def rate_message(message_id: int):
    msg = _owned_message(message_id)
    if not msg:
        return jsonify({"error": "Message not found"}), 404
    if msg.role != "assistant":
        return jsonify({"error": "Only assistant messages can be rated"}), 400

    data = request.get_json() or {}
    rating = data.get("rating")
    if rating not in ("up", "down", None):
        return jsonify({"error": "rating must be 'up', 'down', or null"}), 400

    meta = dict(msg.meta or {})
    current = meta.get("rating")
    if rating == current:
        meta.pop("rating", None)
        new_rating = None
    else:
        meta["rating"] = rating
        new_rating = rating

    msg.meta = meta
    db.session.commit()

    return jsonify({"rating": new_rating, "message": _message_dict(msg)})


@chat_bp.route("/artifacts/<int:artifact_id>/download", methods=["GET"])
@login_required
def download_chat_artifact(artifact_id: int):
    artifact = AgentArtifact.query.filter_by(
        id=artifact_id,
        user_id=current_user.id,
    ).first()
    if not artifact or not artifact.file_path:
        return jsonify({"error": "Not found"}), 404
    path = Path(artifact.file_path)
    if not path.exists():
        return jsonify({"error": "File missing"}), 404
    mimetype = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if path.suffix == ".docx"
        else "application/octet-stream"
    )
    return send_file(path, mimetype=mimetype, as_attachment=True, download_name=path.name)
