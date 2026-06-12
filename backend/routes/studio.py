from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, g, jsonify, request, send_file
from flask_login import login_required, current_user

from backend.config import AGENT_OUTPUT_FOLDER
from backend.models import AgentArtifact, StudioSession, TaskResponse, db
from backend.services.event_logger import log_event
from backend.services.framework_generator import framework_to_json, generate_agent_framework
from backend.services.profile_generator import generate_agent_profile
from backend.services.studio_tasks import get_task, resolve_studio_for_field

studio_bp = Blueprint("studio", __name__, url_prefix="/api/studio")

MIN_TASKS_FOR_AGENT = 1


def _profile_context(profile) -> dict:
    if not profile:
        return {}
    return {
        "full_name": profile.full_name,
        "field": profile.field,
        "industry": profile.industry,
        "skillset": profile.skillset,
        "current_job": profile.current_job,
    }


def _session_context(session: StudioSession | None, profile) -> dict:
    if session and session.agent_context:
        return session.agent_context
    return _profile_context(profile)


def _field_for_session(session: StudioSession | None, profile) -> str:
    ctx = _session_context(session, profile)
    return ctx.get("field") or (profile.field if profile else "data_analyst")


def _template_for_session(session: StudioSession | None, profile) -> dict:
    return resolve_studio_for_field(_field_for_session(session, profile))


def _active_session(user) -> StudioSession | None:
    return (
        StudioSession.query.filter_by(user_id=user.id, status="in_progress")
        .order_by(StudioSession.started_at.desc())
        .first()
    )


def _responses_for_session(session: StudioSession) -> list[dict]:
    return [
        {
            "task_id": r.task_id,
            "task_type": r.task_type,
            "response_data": r.response_data,
            "time_spent_seconds": r.time_spent_seconds,
            "revision_count": r.revision_count,
        }
        for r in session.task_responses
    ]


def _training_progress(session: StudioSession, template: dict) -> dict:
    completed = len(session.task_responses)
    total = len(template["tasks"])
    return {
        "completed": completed,
        "total": total,
        "has_more": completed < total and session.status == "in_progress",
        "all_complete": session.status == "completed",
    }


def _session_payload(session: StudioSession, template: dict) -> dict:
    task = get_task(template, session.current_task_index)
    completed_ids = {r.task_id for r in session.task_responses}
    progress = _training_progress(session, template)

    if session.status == "completed":
        status = "completed"
    elif session.agent_generated_at:
        status = "agent_ready"
    else:
        status = "in_progress"

    return {
        "status": status,
        "session_id": session.id,
        "current_task_index": session.current_task_index,
        "total_tasks": progress["total"],
        "tasks_completed": progress["completed"],
        "has_more_tasks": progress["has_more"],
        "completed_task_ids": list(completed_ids),
        "current_task": task,
        "studio_name": template["name"],
        "agent_generated_at": session.agent_generated_at.isoformat() if session.agent_generated_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    }


@studio_bp.route("/template", methods=["GET"])
@login_required
def get_template():
    session = _active_session(current_user)
    profile = current_user.profile
    template = _template_for_session(session, profile)
    return jsonify(template)


@studio_bp.route("/start", methods=["POST"])
@login_required
def start_studio():
    profile = current_user.profile
    if not profile or not profile.completed_background:
        return jsonify({"error": "Complete your background profile first"}), 400

    existing = _active_session(current_user)
    if existing:
        return jsonify({"session_id": existing.id, "resumed": True})

    data = request.get_json(silent=True) or {}
    context = {
        "full_name": data.get("full_name") or profile.full_name,
        "field": data.get("field") or profile.field,
        "industry": data.get("industry") or profile.industry,
        "skillset": data.get("skillset") or profile.skillset,
        "current_job": data.get("current_job") or profile.current_job,
    }
    template = resolve_studio_for_field(context["field"])

    session = StudioSession(
        user_id=current_user.id,
        studio_template=template["id"],
        status="in_progress",
        current_task_index=0,
        agent_context=context,
    )
    db.session.add(session)
    db.session.commit()

    g.current_user_id = current_user.id
    log_event("studio_started", {"studio_template": template["id"]}, session_id=str(session.id))

    return jsonify({"session_id": session.id, "resumed": False})


@studio_bp.route("/session", methods=["GET"])
@login_required
def get_session():
    session = _active_session(current_user)
    profile = current_user.profile
    template = _template_for_session(session, profile)

    if session:
        return jsonify(_session_payload(session, template))

    completed = (
        StudioSession.query.filter_by(user_id=current_user.id, status="completed")
        .order_by(StudioSession.completed_at.desc())
        .first()
    )
    if completed:
        template = _template_for_session(completed, profile)
        progress = _training_progress(completed, template)
        return jsonify({
            "status": "completed",
            "session_id": completed.id,
            "tasks_completed": progress["completed"],
            "total_tasks": progress["total"],
            "has_more_tasks": False,
            "completed_at": completed.completed_at.isoformat() if completed.completed_at else None,
            "agent_generated_at": completed.agent_generated_at.isoformat() if completed.agent_generated_at else None,
        })

    return jsonify({"status": "not_started"})


@studio_bp.route("/task/submit", methods=["POST"])
@login_required
def submit_task():
    data = request.get_json() or {}
    session = _active_session(current_user)
    if not session:
        return jsonify({"error": "No active studio session"}), 400

    profile = current_user.profile
    template = _template_for_session(session, profile)
    task = get_task(template, session.current_task_index)
    if not task:
        return jsonify({"error": "No current task"}), 400

    task_id = data.get("task_id")
    if task_id != task["id"]:
        return jsonify({"error": "Task mismatch"}), 400

    existing = TaskResponse.query.filter_by(session_id=session.id, task_id=task_id).first()
    if existing:
        existing.response_data = data.get("response_data", {})
        existing.time_spent_seconds = data.get("time_spent_seconds", existing.time_spent_seconds)
        existing.revision_count = (existing.revision_count or 0) + 1
        event_type = "studio_task_revised"
        is_new_task = False
    else:
        existing = TaskResponse(
            session_id=session.id,
            task_id=task_id,
            task_type=task["type"],
            response_data=data.get("response_data", {}),
            time_spent_seconds=data.get("time_spent_seconds"),
            revision_count=0,
        )
        db.session.add(existing)
        event_type = "studio_task_completed"
        session.current_task_index += 1
        is_new_task = True

    g.current_user_id = current_user.id
    log_event(event_type, {
        "task_id": task_id,
        "task_type": task["type"],
        "time_spent_seconds": data.get("time_spent_seconds"),
        "task_index": session.current_task_index - 1 if is_new_task else session.current_task_index,
    }, session_id=str(session.id))

    db.session.flush()
    tasks_completed = len(session.task_responses)
    agent_ready = False

    if is_new_task and tasks_completed >= MIN_TASKS_FOR_AGENT:
        _generate_artifacts(current_user, session, profile, template)
        session.agent_generated_at = datetime.now(timezone.utc)
        agent_ready = True
        log_event("agent_artifacts_generated", {
            "session_id": session.id,
            "tasks_completed": tasks_completed,
            "partial": tasks_completed < len(template["tasks"]),
        }, session_id=str(session.id))

    if session.current_task_index >= len(template["tasks"]):
        session.status = "completed"
        session.completed_at = datetime.now(timezone.utc)
        log_event("studio_completed", {"studio_template": session.studio_template}, session_id=str(session.id))

    db.session.commit()

    progress = _training_progress(session, template)
    next_task = get_task(template, session.current_task_index) if session.status == "in_progress" else None

    return jsonify({
        "ok": True,
        "session_status": session.status,
        "current_task_index": session.current_task_index,
        "tasks_completed": progress["completed"],
        "total_tasks": progress["total"],
        "has_more_tasks": progress["has_more"],
        "agent_ready": agent_ready or bool(session.agent_generated_at),
        "next_task": next_task,
    })


def _generate_artifacts(user, session: StudioSession, profile, template: dict) -> None:
    AGENT_OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    user_dir = AGENT_OUTPUT_FOLDER / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)

    db.session.flush()
    responses = _responses_for_session(session)
    ctx = _session_context(session, profile)
    profile_dict = {
        "full_name": ctx.get("full_name") or profile.full_name,
        "field": ctx.get("field") or profile.field,
        "skillset": ctx.get("skillset") or profile.skillset,
        "current_job": ctx.get("current_job") or profile.current_job,
        "industry": ctx.get("industry") or profile.industry,
        "years_experience": profile.years_experience,
    }

    tasks_completed = len(responses)
    total_tasks = len(template.get("tasks", []))
    field = profile_dict["field"] or "data_analyst"

    md_content = generate_agent_profile(
        profile_dict, responses, field,
        tasks_completed=tasks_completed, total_tasks=total_tasks,
    )
    md_path = user_dir / f"agent-profile-{session.id}.md"
    md_path.write_text(md_content, encoding="utf-8")

    framework = generate_agent_framework(profile_dict, responses)
    json_content = framework_to_json(framework)
    from backend.services.agent_builder import artifact_download_filename

    agent_name = profile_dict.get("full_name") or "agent"
    json_filename = artifact_download_filename("agent_framework_json", agent_name) or f"agent-framework-{session.id}.json"
    json_path = user_dir / json_filename
    json_path.write_text(json_content, encoding="utf-8")

    for artifact_type, path, preview in [
        ("agent_profile_md", md_path, md_content[:500]),
        ("agent_framework_json", json_path, json_content[:500]),
    ]:
        artifact = AgentArtifact.query.filter_by(
            user_id=user.id, session_id=session.id, artifact_type=artifact_type,
        ).first()
        if artifact:
            artifact.file_path = str(path)
            artifact.content_preview = preview
            artifact.generated_at = datetime.now(timezone.utc)
        else:
            db.session.add(AgentArtifact(
                user_id=user.id,
                session_id=session.id,
                artifact_type=artifact_type,
                file_path=str(path),
                content_preview=preview,
            ))


@studio_bp.route("/artifacts", methods=["GET"])
@login_required
def list_artifacts():
    artifacts = (
        AgentArtifact.query.filter_by(user_id=current_user.id)
        .order_by(AgentArtifact.generated_at.desc())
        .all()
    )
    seen_sessions: set[tuple] = set()
    latest = []
    for a in artifacts:
        key = (a.session_id, a.artifact_type)
        if key not in seen_sessions:
            seen_sessions.add(key)
            latest.append(a)

    return jsonify([
        {
            "id": a.id,
            "artifact_type": a.artifact_type,
            "session_id": a.session_id,
            "generated_at": a.generated_at.isoformat() if a.generated_at else None,
            "preview": a.content_preview,
        }
        for a in latest
    ])


def _artifact_agent_name(artifact: AgentArtifact) -> str | None:
    if not artifact.session_id:
        return None
    session = db.session.get(StudioSession, artifact.session_id)
    if session and session.agent_context:
        name = session.agent_context.get("full_name")
        if name:
            return name
    profile = current_user.profile
    return profile.full_name if profile else None


@studio_bp.route("/artifacts/<int:artifact_id>/download", methods=["GET"])
@login_required
def download_artifact(artifact_id: int):
    from backend.services.agent_builder import artifact_download_filename

    artifact = AgentArtifact.query.filter_by(id=artifact_id, user_id=current_user.id).first()
    if not artifact or not artifact.file_path:
        return jsonify({"error": "Not found"}), 404

    path = Path(artifact.file_path)
    if not path.exists():
        return jsonify({"error": "File missing"}), 404

    mimetype = (
        "text/markdown"
        if artifact.artifact_type in ("agent_profile_md", "agent_skill_md")
        else "application/json"
    )

    agent_name = _artifact_agent_name(artifact)
    download_name = (
        artifact_download_filename(artifact.artifact_type, agent_name)
        if agent_name
        else None
    ) or path.name

    return send_file(path, mimetype=mimetype, as_attachment=True, download_name=download_name)


@studio_bp.route("/artifacts/<int:artifact_id>/content", methods=["GET"])
@login_required
def view_artifact(artifact_id: int):
    artifact = AgentArtifact.query.filter_by(id=artifact_id, user_id=current_user.id).first()
    if not artifact or not artifact.file_path:
        return jsonify({"error": "Not found"}), 404

    path = Path(artifact.file_path)
    if not path.exists():
        return jsonify({"error": "File missing"}), 404

    return jsonify({
        "artifact_type": artifact.artifact_type,
        "content": path.read_text(encoding="utf-8"),
    })
