from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, g, jsonify, request
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from backend.config import AGENT_OUTPUT_FOLDER, UPLOAD_FOLDER
from backend.models import AgentArtifact, ChatMessage, ChatThread, Project, StudioSession, TaskResponse, db
from backend.services.feedback_adaptation import apply_feedback_to_session
from backend.services.feedback_filter import classify_feedback, feedback_status_from_classification
from backend.services.agent_builder import (
    artifact_download_filename,
    build_agent_framework,
    build_agent_profile,
    framework_to_json,
    write_skill_md_file,
)
from backend.services.agent_framework_designer import generate_framework_preview
from backend.services.framework_build_jobs import get_job, start_job
from backend.services.agent_jd_generator import generate_jd_draft
from backend.services.event_logger import log_event
from backend.services.prebuilt_agents import build_agent_context, get_prebuilt, list_prebuilt
from backend.services.chat_threads import ensure_agent_dm_thread
from backend.services.skill_framework import (
    MAX_AGENT_SKILLS,
    build_skill_framework,
    normalize_skillset,
    skills_list,
)
from backend.services.studio_tasks import resolve_studio_for_field
from backend.services.thinking_principles import (
    enrich_agent_context,
    is_platform_skill,
    strip_platform_instruction_blocks,
    user_skills_list,
    user_skillset,
)

agents_bp = Blueprint("agents", __name__, url_prefix="/api/agents")
AGENT_CONTEXT_UPLOAD = UPLOAD_FOLDER / "agent_context"
ALLOWED_CONTEXT_EXTENSIONS = {".csv", ".txt", ".md", ".pdf", ".docx", ".xlsx", ".xls"}
COMMUNICATION_STYLES = frozenset({
    "concise", "professional", "detailed", "direct", "friendly", "collaborative",
})


def _context_from_request(data: dict, profile) -> dict:
    ctx = {
        "full_name": data.get("full_name") or (profile.full_name if profile else None),
        "field": data.get("field") or (profile.field if profile else None),
        "industry": data.get("industry") or (profile.industry if profile else None),
        "skillset": data.get("skillset") or (profile.skillset if profile else None),
        "current_job": data.get("current_job") or (profile.current_job if profile else None),
    }
    if data.get("job_description"):
        ctx["job_description"] = data["job_description"]
    if data.get("framework_design"):
        ctx["framework_design"] = data["framework_design"]
    if ctx.get("skillset"):
        ctx["skillset"] = normalize_skillset(ctx["skillset"])
    return ctx


def _raw_skillset_from_request(data: dict, profile) -> str | None:
    return data.get("skillset") or (profile.skillset if profile else None)


def _skillset_over_limit(data: dict, profile) -> bool:
    raw = _raw_skillset_from_request(data, profile)
    return bool(raw) and len(user_skills_list(raw)) > MAX_AGENT_SKILLS


@agents_bp.route("/jd-draft", methods=["POST"])
@login_required
def jd_draft():
    data = request.get_json() or {}
    profile = current_user.profile
    context = _context_from_request(data, profile)

    if not context.get("field"):
        return jsonify({"error": "Field is required"}), 400

    return jsonify(generate_jd_draft(context))


def _framework_preview_context(data: dict):
    profile = current_user.profile
    if _skillset_over_limit(data, profile):
        return None, None, (
            jsonify({"error": f"Maximum {MAX_AGENT_SKILLS} skills per agent"}),
            400,
        )
    context = _context_from_request(data, profile)
    jd = data.get("job_description")
    if not jd or not jd.get("responsibilities"):
        return None, None, (jsonify({"error": "Confirmed job description is required"}), 400)
    context["job_description"] = jd
    return jd, context, None


@agents_bp.route("/framework-preview", methods=["POST"])
@login_required
def framework_preview():
    data = request.get_json() or {}
    jd, context, err = _framework_preview_context(data)
    if err:
        return err
    return jsonify(generate_framework_preview(jd, context))


@agents_bp.route("/framework-preview/jobs", methods=["POST"])
@login_required
def framework_preview_job_start():
    data = request.get_json() or {}
    jd, context, err = _framework_preview_context(data)
    if err:
        return err

    def build(reporter):
        return generate_framework_preview(jd, context, reporter=reporter)

    job_id = start_job(current_user.id, build)
    return jsonify({"job_id": job_id, "accepted": True}), 202


@agents_bp.route("/framework-preview/jobs/<job_id>", methods=["GET"])
@login_required
def framework_preview_job_status(job_id):
    job = get_job(job_id, current_user.id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


def _owned_session(session_id: int) -> StudioSession | None:
    return StudioSession.query.filter_by(
        id=session_id,
        user_id=current_user.id,
    ).filter(StudioSession.agent_generated_at.isnot(None)).first()


def _delete_artifact_files(artifacts: list[AgentArtifact]) -> None:
    for art in artifacts:
        if not art.file_path:
            continue
        path = Path(art.file_path)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass


def _remove_stale_named_files(user_dir: Path, old_name: str | None, new_name: str | None) -> None:
    if not old_name or old_name == new_name:
        return
    for artifact_type in ("agent_framework_json", "agent_skill_md"):
        filename = artifact_download_filename(artifact_type, old_name)
        if not filename:
            continue
        path = user_dir / filename
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass


def _write_artifact_files(user, session: StudioSession, context: dict) -> list[tuple[str, Path, str]]:
    AGENT_OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    user_dir = AGENT_OUTPUT_FOLDER / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)

    md_content = build_agent_profile(context)
    md_path = user_dir / f"agent-profile-{session.id}.md"
    md_path.write_text(md_content, encoding="utf-8")

    framework = build_agent_framework(context)
    json_content = framework_to_json(framework)
    agent_name = context.get("full_name") or "agent"
    json_filename = artifact_download_filename("agent_framework_json", agent_name)
    json_path = user_dir / json_filename
    json_path.write_text(json_content, encoding="utf-8")

    artifacts = [
        ("agent_profile_md", md_path, md_content[:500]),
        ("agent_framework_json", json_path, json_content[:500]),
    ]
    skill_result = write_skill_md_file(user_dir, context)
    if skill_result:
        skill_path, skill_preview = skill_result
        artifacts.append(("agent_skill_md", skill_path, skill_preview))
    return artifacts


def _regenerate_artifacts(
    user,
    session: StudioSession,
    context: dict,
    old_context: dict | None = None,
) -> None:
    existing = AgentArtifact.query.filter_by(
        user_id=user.id,
        session_id=session.id,
    ).all()
    _delete_artifact_files(existing)
    for art in existing:
        db.session.delete(art)

    user_dir = AGENT_OUTPUT_FOLDER / str(user.id)
    _remove_stale_named_files(
        user_dir,
        (old_context or {}).get("full_name"),
        context.get("full_name"),
    )

    for artifact_type, path, preview in _write_artifact_files(user, session, context):
        db.session.add(AgentArtifact(
            user_id=user.id,
            session_id=session.id,
            artifact_type=artifact_type,
            file_path=str(path),
            content_preview=preview,
        ))


def _save_artifacts(user, session: StudioSession, context: dict) -> None:
    for artifact_type, path, preview in _write_artifact_files(user, session, context):
        db.session.add(AgentArtifact(
            user_id=user.id,
            session_id=session.id,
            artifact_type=artifact_type,
            file_path=str(path),
            content_preview=preview,
        ))


def _user_agent_sessions() -> list:
    return (
        StudioSession.query.filter_by(user_id=current_user.id)
        .filter(StudioSession.agent_generated_at.isnot(None))
        .all()
    )


def _user_prebuilt_ids() -> set[str]:
    ids: set[str] = set()
    for session in _user_agent_sessions():
        ctx = session.agent_context or {}
        if ctx.get("hidden_from_roster"):
            continue
        pid = ctx.get("prebuilt_id")
        if pid:
            ids.add(pid)
    return ids


def _hidden_prebuilt_session(template_id: str):
    for session in _user_agent_sessions():
        ctx = session.agent_context or {}
        if ctx.get("prebuilt_id") == template_id and ctx.get("hidden_from_roster"):
            return session
    return None


@agents_bp.route("/prebuilt", methods=["GET"])
@login_required
def get_prebuilt_catalog():
    search = request.args.get("search", "")
    added_ids = _user_prebuilt_ids()
    agents = []
    for item in list_prebuilt(search):
        agents.append({**item, "added": item["id"] in added_ids})
    return jsonify({"agents": agents})


@agents_bp.route("/prebuilt/<template_id>/add", methods=["POST"])
@login_required
def add_prebuilt_agent(template_id: str):
    template = get_prebuilt(template_id)
    if not template:
        return jsonify({"error": "Prebuilt agent not found"}), 404

    if template_id in _user_prebuilt_ids():
        return jsonify({"error": "This agent is already in your workspace"}), 409

    hidden_session = _hidden_prebuilt_session(template_id)
    if hidden_session:
        context = dict(hidden_session.agent_context or {})
        context["hidden_from_roster"] = False
        hidden_session.agent_context = context
        db.session.commit()

        g.current_user_id = current_user.id
        log_event("agent_restored_prebuilt", {
            "session_id": hidden_session.id,
            "prebuilt_id": template_id,
        }, session_id=str(hidden_session.id))

        return jsonify({
            "ok": True,
            "session_id": hidden_session.id,
            "agent_name": context.get("full_name"),
            "prebuilt_id": template_id,
            "restored": True,
        })

    context = enrich_agent_context(build_agent_context(template))
    jd_result = generate_jd_draft(context)
    jd = jd_result.get("job_description")
    if not jd or not jd.get("responsibilities"):
        return jsonify({"error": "Could not generate job description for template"}), 500

    context["job_description"] = jd
    fw_result = generate_framework_preview(jd, context)
    framework = fw_result.get("framework")
    if not framework:
        return jsonify({"error": "Could not generate framework for template"}), 500

    context["framework_design"] = {
        "framework": framework,
        "construction_answers": {},
    }

    studio_template = resolve_studio_for_field(context["field"])
    session = StudioSession(
        user_id=current_user.id,
        studio_template=studio_template["id"],
        status="configured",
        current_task_index=0,
        agent_context=context,
        agent_generated_at=datetime.now(timezone.utc),
    )
    db.session.add(session)
    db.session.flush()

    _save_artifacts(current_user, session, context)
    ensure_agent_dm_thread(current_user.id, session)
    db.session.commit()

    g.current_user_id = current_user.id
    log_event("agent_added_prebuilt", {
        "session_id": session.id,
        "prebuilt_id": template_id,
        "field": context["field"],
    }, session_id=str(session.id))

    return jsonify({
        "ok": True,
        "session_id": session.id,
        "agent_name": context["full_name"],
        "prebuilt_id": template_id,
    })


@agents_bp.route("/create", methods=["POST"])
@login_required
def create_agent():
    profile = current_user.profile
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    data = request.get_json() or {}
    if _skillset_over_limit(data, profile):
        return jsonify({"error": f"Maximum {MAX_AGENT_SKILLS} skills per agent"}), 400
    context = enrich_agent_context(_context_from_request(data, profile))

    if not context.get("full_name"):
        return jsonify({"error": "Agent name is required"}), 400
    if not context.get("field"):
        return jsonify({"error": "Field is required"}), 400
    if not context.get("skillset"):
        return jsonify({"error": "At least one skill is required"}), 400
    if not context.get("job_description"):
        return jsonify({"error": "Job description is required"}), 400

    template = resolve_studio_for_field(context["field"])

    session = StudioSession(
        user_id=current_user.id,
        studio_template=template["id"],
        status="configured",
        current_task_index=0,
        agent_context=context,
        agent_generated_at=datetime.now(timezone.utc),
    )
    db.session.add(session)
    db.session.flush()

    _save_artifacts(current_user, session, context)
    ensure_agent_dm_thread(current_user.id, session)
    db.session.commit()

    g.current_user_id = current_user.id
    log_event("agent_created", {
        "session_id": session.id,
        "field": context["field"],
        "source": "jd_framework",
    }, session_id=str(session.id))

    return jsonify({
        "ok": True,
        "session_id": session.id,
        "agent_name": context["full_name"],
    })


def _maybe_sanitize_stored_context(session, ctx: dict) -> dict:
    """Strip legacy platform defaults from persisted agent context."""
    clean_skillset = user_skillset(ctx.get("skillset"))
    clean_instructions = strip_platform_instruction_blocks(ctx.get("working_instructions")) or None
    dirty = (
        ctx.get("skillset") != clean_skillset
        or (ctx.get("working_instructions") or None) != clean_instructions
    )
    if not dirty:
        return ctx
    updated = {**ctx, "skillset": clean_skillset, "working_instructions": clean_instructions}
    session.agent_context = updated
    db.session.commit()
    return updated


@agents_bp.route("/<int:session_id>", methods=["GET"])
@login_required
def get_agent(session_id: int):
    session = _owned_session(session_id)
    if not session:
        return jsonify({"error": "Agent not found"}), 404

    ctx = _maybe_sanitize_stored_context(session, dict(session.agent_context or {}))
    visible_skills = user_skills_list(ctx.get("skillset"))
    return jsonify({
        "session_id": session.id,
        "status": session.status,
        "agent_name": ctx.get("full_name"),
        "field": ctx.get("field"),
        "industry": ctx.get("industry"),
        "current_job": ctx.get("current_job"),
        "skillset": user_skillset(ctx.get("skillset")),
        "skills": visible_skills,
        "job_description": ctx.get("job_description"),
        "framework_design": ctx.get("framework_design"),
        "working_instructions": strip_platform_instruction_blocks(ctx.get("working_instructions")) or None,
        "context_files": ctx.get("context_files") or [],
        "agent_context": {
            **ctx,
            "skillset": user_skillset(ctx.get("skillset")),
            "working_instructions": strip_platform_instruction_blocks(ctx.get("working_instructions")) or None,
        },
    })


@agents_bp.route("/<int:session_id>/skills", methods=["PUT"])
@login_required
def update_agent_skills(session_id: int):
    session = _owned_session(session_id)
    if not session:
        return jsonify({"error": "Agent not found"}), 404

    data = request.get_json() or {}
    raw_skills = data.get("skills")
    if raw_skills is None and data.get("skillset"):
        raw_skills = skills_list(data["skillset"])
    if not isinstance(raw_skills, list):
        return jsonify({"error": "skills must be a list"}), 400

    skills = []
    seen: set[str] = set()
    for item in raw_skills:
        name = (item or "").strip()
        if not name or is_platform_skill(name):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        skills.append(name)
        if len(skills) >= MAX_AGENT_SKILLS:
            break

    if not skills:
        return jsonify({"error": "At least one skill is required"}), 400

    old_context = dict(session.agent_context or {})
    context = dict(old_context)
    context["skillset"] = ", ".join(skills)

    jd = dict(context.get("job_description") or {})
    if not jd.get("responsibilities"):
        jd = {
            **jd,
            "title": jd.get("title") or f"{context.get('field', 'Professional')} — {context.get('full_name', 'Agent')}",
            "summary": jd.get("summary") or f"Specialist agent for {context.get('full_name', 'Agent')}.",
            "responsibilities": [
                f"Apply {s} to deliverables aligned with this role." for s in skills[:4]
            ] or ["Handle user requests within assigned skills."],
        }
        context["job_description"] = jd

    built = build_skill_framework(jd, context, from_user_skills_only=True)
    framework_design = dict(context.get("framework_design") or {})
    framework_design["framework"] = built.get("framework") or built
    context["framework_design"] = framework_design

    session.agent_context = context
    session.agent_generated_at = datetime.now(timezone.utc)
    _regenerate_artifacts(current_user, session, context, old_context)
    db.session.commit()

    fw = framework_design.get("framework") or {}
    skill_agents = [
        a for a in fw.get("agents", [])
        if a.get("type") == "skill" or str(a.get("id", "")).startswith("skill_")
    ]

    return jsonify({
        "ok": True,
        "skillset": context["skillset"],
        "skills": skills,
        "subagents": [
            {
                "skill": a.get("skill"),
                "member_skills": a.get("member_skills") or [a.get("skill")],
            }
            for a in skill_agents
        ],
    })


@agents_bp.route("/<int:session_id>/working-context", methods=["PUT"])
@login_required
def update_working_context(session_id: int):
    session = _owned_session(session_id)
    if not session:
        return jsonify({"error": "Agent not found"}), 404

    data = request.get_json() or {}
    context = dict(session.agent_context or {})
    if "working_instructions" in data:
        text = strip_platform_instruction_blocks(data.get("working_instructions"))
        context["working_instructions"] = text or None
    if "communication_style" in data:
        style = (data.get("communication_style") or "").strip().lower()
        if style and style not in COMMUNICATION_STYLES:
            return jsonify({"error": "Invalid communication style"}), 400
        context["communication_style"] = style or None

    session.agent_context = context
    db.session.commit()

    return jsonify({
        "working_instructions": context.get("working_instructions"),
        "communication_style": context.get("communication_style"),
        "context_files": context.get("context_files") or [],
    })


@agents_bp.route("/<int:session_id>/feedback", methods=["GET"])
@login_required
def list_dm_agent_feedback(session_id: int):
    session = _owned_session(session_id)
    if not session:
        return jsonify({"error": "Agent not found"}), 404

    ctx = session.agent_context or {}
    digest = ctx.get("feedback_digest") or []
    feedback = [
        {
            "content": entry.get("content", ""),
            "status": "approved",
            "applied_at": entry.get("applied_at"),
        }
        for entry in reversed(digest[-10:])
    ]
    return jsonify({"feedback": feedback})


@agents_bp.route("/<int:session_id>/feedback", methods=["POST"])
@login_required
def submit_dm_agent_feedback(session_id: int):
    session = _owned_session(session_id)
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
            agent_session_id=session_id,
        ).first()
        if thread:
            last = (
                ChatMessage.query.filter_by(thread_id=thread.id, role="assistant")
                .order_by(ChatMessage.created_at.desc())
                .first()
            )
            if last:
                recent_snippet = (last.content or "")[:800]

    classification = classify_feedback(
        content,
        session.agent_context or {},
        recent_assistant_snippet=recent_snippet,
    )
    status = feedback_status_from_classification(classification)

    message = "Feedback submitted."
    if status == "approved":
        apply_feedback_to_session(session, content)
        db.session.commit()
        message = "Feedback applied — the agent will incorporate this going forward."
    else:
        message = (
            f"Feedback not applied: {classification.get('reason') or 'Not relevant to agent skills.'}"
        )

    return jsonify({
        "status": status,
        "filter_reason": classification.get("reason"),
        "message": message,
    }), 201


@agents_bp.route("/<int:session_id>/working-context/files", methods=["POST"])
@login_required
def upload_working_context_file(session_id: int):
    session = _owned_session(session_id)
    if not session:
        return jsonify({"error": "Agent not found"}), 404

    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "File is required"}), 400

    ext = Path(upload.filename).suffix.lower()
    if ext not in ALLOWED_CONTEXT_EXTENSIONS:
        return jsonify({"error": f"Unsupported file type: {ext}"}), 400

    AGENT_CONTEXT_UPLOAD.mkdir(parents=True, exist_ok=True)
    safe = secure_filename(upload.filename)
    dest = AGENT_CONTEXT_UPLOAD / f"{current_user.id}_{session_id}_{safe}"
    upload.save(dest)

    context = dict(session.agent_context or {})
    files = list(context.get("context_files") or [])
    files.append({
        "filename": upload.filename,
        "path": str(dest),
        "size_bytes": dest.stat().st_size,
    })
    context["context_files"] = files
    session.agent_context = context
    db.session.commit()

    return jsonify({
        "working_instructions": context.get("working_instructions"),
        "context_files": files,
    })


@agents_bp.route("/<int:session_id>", methods=["PUT"])
@login_required
def update_agent(session_id: int):
    session = _owned_session(session_id)
    if not session:
        return jsonify({"error": "Agent not found"}), 404

    profile = current_user.profile
    data = request.get_json() or {}
    if _skillset_over_limit(data, profile):
        return jsonify({"error": f"Maximum {MAX_AGENT_SKILLS} skills per agent"}), 400
    old_context = dict(session.agent_context or {})
    context = {**old_context, **_context_from_request(data, profile)}

    if data.get("job_description") is not None:
        context["job_description"] = data["job_description"]
    if data.get("framework_design") is not None:
        context["framework_design"] = data["framework_design"]

    if not context.get("full_name"):
        return jsonify({"error": "Agent name is required"}), 400
    if not context.get("field"):
        return jsonify({"error": "Field is required"}), 400
    if not context.get("skillset"):
        return jsonify({"error": "At least one skill is required"}), 400

    session.agent_context = context
    session.agent_generated_at = datetime.now(timezone.utc)
    _regenerate_artifacts(current_user, session, context, old_context)
    db.session.commit()

    g.current_user_id = current_user.id
    log_event("agent_updated", {
        "session_id": session.id,
        "field": context.get("field"),
    }, session_id=str(session.id))

    return jsonify({
        "ok": True,
        "session_id": session.id,
        "agent_name": context["full_name"],
    })


@agents_bp.route("/<int:session_id>/hide-from-roster", methods=["POST"])
@login_required
def hide_agent_from_roster(session_id: int):
    """Remove agent from AI agents roster; keep chats and history."""
    session = _owned_session(session_id)
    if not session:
        return jsonify({"error": "Agent not found"}), 404

    context = dict(session.agent_context or {})
    if context.get("hidden_from_roster"):
        return jsonify({"ok": True, "session_id": session.id, "hidden_from_roster": True})

    context["hidden_from_roster"] = True
    session.agent_context = context
    db.session.commit()

    g.current_user_id = current_user.id
    log_event("agent_hidden_from_roster", {"session_id": session_id}, session_id=str(session_id))

    return jsonify({
        "ok": True,
        "session_id": session.id,
        "hidden_from_roster": True,
        "agent_name": context.get("full_name"),
    })


@agents_bp.route("/<int:session_id>", methods=["DELETE"])
@login_required
def delete_agent(session_id: int):
    session = _owned_session(session_id)
    if not session:
        return jsonify({"error": "Agent not found"}), 404

    ctx = session.agent_context or {}
    artifacts = AgentArtifact.query.filter_by(
        user_id=current_user.id,
        session_id=session.id,
    ).all()
    _delete_artifact_files(artifacts)

    user_dir = AGENT_OUTPUT_FOLDER / str(current_user.id)
    _remove_stale_named_files(user_dir, ctx.get("full_name"), None)

    profile_path = user_dir / f"agent-profile-{session.id}.md"
    if profile_path.exists():
        try:
            profile_path.unlink()
        except OSError:
            pass

    skills_legacy = user_dir / f"skills-{session.id}"
    if skills_legacy.is_dir():
        for f in skills_legacy.glob("*"):
            try:
                f.unlink()
            except OSError:
                pass
        try:
            skills_legacy.rmdir()
        except OSError:
            pass

    for art in artifacts:
        db.session.delete(art)
    for thread in ChatThread.query.filter_by(agent_session_id=session.id).all():
        db.session.delete(thread)
    for project in Project.query.filter_by(user_id=current_user.id).all():
        ids = list(project.agent_session_ids or [])
        if session.id in ids:
            ids.remove(session.id)
            project.agent_session_ids = ids
    for thread in ChatThread.query.filter(
        ChatThread.user_id == current_user.id,
        ChatThread.participant_agent_ids.isnot(None),
    ).all():
        if thread.participant_agent_ids and session.id in thread.participant_agent_ids:
            db.session.delete(thread)
    TaskResponse.query.filter_by(session_id=session.id).delete()
    db.session.delete(session)
    db.session.commit()

    g.current_user_id = current_user.id
    log_event("agent_deleted", {"session_id": session_id}, session_id=str(session_id))

    return jsonify({"ok": True})
