"""Project workspaces — multi-agent, instructions, Supabase file context, feedback."""

from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from backend.models import (
    AgentFeedback,
    ChatMessage,
    ChatThread,
    Project,
    StudioSession,
    db,
)
from backend.services.agent_builder import build_agent_framework
from backend.services.chat_orchestrator import welcome_message
from backend.services.feedback_adaptation import apply_approved_feedback
from backend.services.feedback_filter import classify_feedback, feedback_status_from_classification
from backend.services.supabase_storage import (
    StorageNotConfiguredError,
    delete_project_file,
    upload_project_file,
)

projects_bp = Blueprint("projects", __name__, url_prefix="/api/projects")
ALLOWED_EXTENSIONS = {".csv", ".txt", ".md", ".pdf", ".docx", ".xlsx", ".xls"}


def _owned_project(project_id: int) -> Project | None:
    return Project.query.filter_by(id=project_id, user_id=current_user.id).first()


def _agent_label(session_id: int) -> dict:
    session = db.session.get(StudioSession, session_id)
    ctx = (session.agent_context or {}) if session else {}
    return {
        "name": ctx.get("full_name") or "Agent",
        "job_title": ctx.get("current_job"),
        "field": ctx.get("field"),
    }


def _validate_agent_ids(agent_ids: list) -> list[int]:
    if not agent_ids:
        return []
    valid = []
    for aid in agent_ids:
        session = StudioSession.query.filter_by(
            id=int(aid),
            user_id=current_user.id,
        ).filter(StudioSession.agent_generated_at.isnot(None)).first()
        if session:
            valid.append(session.id)
    return valid


def _project_agent_thread(project: Project, session_id: int) -> ChatThread | None:
    return ChatThread.query.filter_by(
        user_id=current_user.id,
        project_id=project.id,
        agent_session_id=session_id,
        thread_type="project_agent",
    ).first()


def _create_project_agent_thread(project: Project, session_id: int) -> ChatThread:
    existing = _project_agent_thread(project, session_id)
    if existing:
        return existing

    session = db.session.get(StudioSession, session_id)
    label = _agent_label(session_id)
    thread = ChatThread(
        user_id=current_user.id,
        thread_type="project_agent",
        project_id=project.id,
        agent_session_id=session_id,
        title=f"{project.name} · {label['name']}",
    )
    db.session.add(thread)
    db.session.flush()

    if session:
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
    return thread


def _sync_project_agent_threads(project: Project, new_agent_ids: list[int]) -> None:
    for sid in new_agent_ids:
        if sid in (project.agent_session_ids or []):
            _create_project_agent_thread(project, sid)


def _project_agents(project: Project) -> list[dict]:
    agents = []
    for sid in project.agent_session_ids or []:
        label = _agent_label(sid)
        thread = _project_agent_thread(project, sid)
        agents.append({
            "session_id": sid,
            "name": label["name"],
            "job_title": label["job_title"],
            "thread_id": thread.id if thread else None,
        })
    return agents


def _project_dict(project: Project, include_agents: bool = True) -> dict:
    data = {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "instructions": project.instructions,
        "agent_session_ids": project.agent_session_ids or [],
        "context_files": project.context_files or [],
        "pinned": project.pinned,
        "sort_order": project.sort_order,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }
    if include_agents:
        data["agents"] = _project_agents(project)
        first_thread = (
            ChatThread.query.filter_by(project_id=project.id, thread_type="project_agent")
            .order_by(ChatThread.created_at.asc())
            .first()
        )
        data["thread_id"] = first_thread.id if first_thread else None
    return data


def _feedback_dict(entry: AgentFeedback) -> dict:
    return {
        "id": entry.id,
        "content": entry.content,
        "status": entry.status,
        "filter_score": entry.filter_score,
        "filter_reason": entry.filter_reason,
        "filter_categories": entry.filter_categories or [],
        "applied_at": entry.applied_at.isoformat() if entry.applied_at else None,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


@projects_bp.route("", methods=["GET"])
@login_required
def list_projects():
    sort = request.args.get("sort", "updated")
    q = Project.query.filter_by(user_id=current_user.id)
    if sort == "name":
        projects = q.order_by(Project.name.asc()).all()
    elif sort == "created":
        projects = q.order_by(Project.created_at.desc()).all()
    else:
        projects = q.order_by(Project.pinned.desc(), Project.updated_at.desc()).all()
    return jsonify({
        "projects": [_project_dict(p, include_agents=False) for p in projects],
    })


@projects_bp.route("", methods=["POST"])
@login_required
def create_project():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Project name is required"}), 400

    agent_ids = _validate_agent_ids(data.get("agent_session_ids") or [])
    project = Project(
        user_id=current_user.id,
        name=name,
        description=(data.get("description") or "").strip() or None,
        instructions=(data.get("instructions") or "").strip() or None,
        agent_session_ids=agent_ids,
        pinned=bool(data.get("pinned")),
    )
    db.session.add(project)
    db.session.flush()
    _sync_project_agent_threads(project, agent_ids)
    project.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(_project_dict(project)), 201


@projects_bp.route("/<int:project_id>", methods=["GET"])
@login_required
def get_project(project_id: int):
    project = _owned_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    return jsonify(_project_dict(project))


@projects_bp.route("/<int:project_id>", methods=["PUT"])
@login_required
def update_project(project_id: int):
    project = _owned_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    data = request.get_json() or {}
    old_ids = set(project.agent_session_ids or [])

    if "name" in data:
        name = (data["name"] or "").strip()
        if name:
            project.name = name
    if "description" in data:
        project.description = (data["description"] or "").strip() or None
    if "instructions" in data:
        project.instructions = (data["instructions"] or "").strip() or None
    if "agent_session_ids" in data:
        project.agent_session_ids = _validate_agent_ids(data["agent_session_ids"] or [])
    if "pinned" in data:
        project.pinned = bool(data["pinned"])
    if "sort_order" in data:
        project.sort_order = int(data["sort_order"])

    new_ids = set(project.agent_session_ids or [])
    for sid in new_ids - old_ids:
        _create_project_agent_thread(project, sid)

    project.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(_project_dict(project))


@projects_bp.route("/<int:project_id>", methods=["DELETE"])
@login_required
def delete_project(project_id: int):
    project = _owned_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    for f in project.context_files or []:
        storage_path = f.get("storage_path")
        if storage_path:
            try:
                delete_project_file(storage_path)
            except Exception:
                pass

    db.session.delete(project)
    db.session.commit()
    return jsonify({"ok": True})


@projects_bp.route("/<int:project_id>/files", methods=["POST"])
@login_required
def upload_project_file_route(project_id: int):
    project = _owned_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "File is required"}), 400

    ext = Path(upload.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Unsupported file type: {ext}"}), 400

    data = upload.read()
    try:
        meta = upload_project_file(current_user.id, project_id, upload.filename, data)
    except StorageNotConfiguredError as exc:
        return jsonify({"error": str(exc)}), 503

    files = list(project.context_files or [])
    files.append(meta)
    project.context_files = files
    project.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(_project_dict(project))


@projects_bp.route("/<int:project_id>/files/<int:file_index>", methods=["DELETE"])
@login_required
def delete_project_file_route(project_id: int, file_index: int):
    project = _owned_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    files = list(project.context_files or [])
    if file_index < 0 or file_index >= len(files):
        return jsonify({"error": "File not found"}), 404

    entry = files.pop(file_index)
    storage_path = entry.get("storage_path")
    if storage_path:
        try:
            delete_project_file(storage_path)
        except Exception:
            pass

    project.context_files = files
    project.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(_project_dict(project))


@projects_bp.route("/<int:project_id>/agents/<int:session_id>/feedback", methods=["POST"])
@login_required
def submit_agent_feedback(project_id: int, session_id: int):
    project = _owned_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    if session_id not in (project.agent_session_ids or []):
        return jsonify({"error": "Agent is not assigned to this project"}), 400

    session = StudioSession.query.filter_by(
        id=session_id,
        user_id=current_user.id,
    ).first()
    if not session:
        return jsonify({"error": "Agent not found"}), 404

    data = request.get_json() or {}
    content = (data.get("content") or "").strip()
    if len(content) < 10:
        return jsonify({"error": "Feedback must be at least 10 characters"}), 400

    thread_id = data.get("thread_id")
    recent_snippet = None
    if thread_id:
        thread = ChatThread.query.filter_by(
            id=int(thread_id),
            user_id=current_user.id,
            project_id=project_id,
        ).first()
        if thread:
            last = (
                ChatMessage.query.filter_by(thread_id=thread.id, role="assistant")
                .order_by(ChatMessage.created_at.desc())
                .first()
            )
            if last:
                recent_snippet = (last.content or "")[:800]

    entry = AgentFeedback(
        user_id=current_user.id,
        project_id=project_id,
        agent_session_id=session_id,
        thread_id=int(thread_id) if thread_id else None,
        content=content,
        status="pending",
    )
    db.session.add(entry)
    db.session.flush()

    classification = classify_feedback(
        content,
        session.agent_context or {},
        project_name=project.name,
        project_instructions=project.instructions,
        recent_assistant_snippet=recent_snippet,
    )
    entry.status = feedback_status_from_classification(classification)
    entry.filter_score = classification.get("score")
    entry.filter_reason = classification.get("reason")
    entry.filter_categories = classification.get("categories") or []

    message = "Feedback submitted."
    if entry.status == "approved":
        apply_approved_feedback(entry)
        message = "Feedback applied — the agent will incorporate this going forward."
    else:
        db.session.commit()
        message = f"Feedback saved but not applied: {entry.filter_reason or 'Not relevant to agent skills.'}"

    return jsonify({
        "id": entry.id,
        "status": entry.status,
        "filter_reason": entry.filter_reason,
        "message": message,
        **_feedback_dict(entry),
    }), 201


@projects_bp.route("/<int:project_id>/agents/<int:session_id>/feedback", methods=["GET"])
@login_required
def list_agent_feedback(project_id: int, session_id: int):
    project = _owned_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    entries = (
        AgentFeedback.query.filter_by(
            user_id=current_user.id,
            project_id=project_id,
            agent_session_id=session_id,
        )
        .order_by(AgentFeedback.created_at.desc())
        .limit(20)
        .all()
    )
    return jsonify({"feedback": [_feedback_dict(e) for e in entries]})
