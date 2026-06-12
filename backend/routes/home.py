import json
from pathlib import Path

from flask import Blueprint, jsonify
from flask_login import login_required, current_user

from backend.models import AgentArtifact, StudioSession, TaskResponse
from backend.services.studio_tasks import resolve_studio_for_field

home_bp = Blueprint("home", __name__, url_prefix="/api/home")

FIELD_ICONS = {
    "data analytics": "📊",
    "data science": "🔬",
    "product analytics": "📈",
    "product management": "🎯",
    "marketing": "📣",
    "finance": "💰",
    "software engineering": "💻",
    "ux": "🎨",
    "sales": "🤝",
    "operations": "⚙️",
    "people": "👥",
    "consulting": "💼",
}


def _persona_icon(field: str | None) -> str:
    if not field:
        return "✦"
    return FIELD_ICONS.get(field.lower(), "✦")


def _initials(name: str | None) -> str:
    if not name:
        return "?"
    parts = name.strip().split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return name[:2].upper()


def _load_framework_summary(artifact: AgentArtifact) -> dict | None:
    if not artifact.file_path:
        return None
    path = Path(artifact.file_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    agents = [
        {
            "id": a.get("id"),
            "role": a.get("role"),
            "skill": a.get("skill"),
            "type": a.get("type"),
            "triggers": a.get("triggers", []),
        }
        for a in data.get("agents", [])
    ]
    return {
        "orchestrator": data.get("orchestrator", {}).get("description"),
        "routing_rules": data.get("orchestrator", {}).get("routing_rules", []),
        "manager": data.get("manager"),
        "skill_breakdown": data.get("skill_breakdown", []),
        "interactions": data.get("interactions", []),
        "agents": agents,
        "style_profile": data.get("style_profile", {}),
        "training_progress": data.get("training_progress", {}),
    }


def _load_profile_preview(artifact: AgentArtifact) -> str | None:
    if not artifact.file_path:
        return None
    path = Path(artifact.file_path)
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


@home_bp.route("", methods=["GET"])
@login_required
def get_home():
    profile = current_user.profile
    sessions = (
        StudioSession.query.filter_by(user_id=current_user.id)
        .filter(StudioSession.agent_generated_at.isnot(None))
        .order_by(StudioSession.agent_generated_at.desc())
        .all()
    )

    personas = []
    for session in sessions:
        md_artifact = AgentArtifact.query.filter_by(
            user_id=current_user.id,
            session_id=session.id,
            artifact_type="agent_profile_md",
        ).order_by(AgentArtifact.generated_at.desc()).first()
        json_artifact = AgentArtifact.query.filter_by(
            user_id=current_user.id,
            session_id=session.id,
            artifact_type="agent_framework_json",
        ).order_by(AgentArtifact.generated_at.desc()).first()
        skill_artifact = AgentArtifact.query.filter_by(
            user_id=current_user.id,
            session_id=session.id,
            artifact_type="agent_skill_md",
        ).order_by(AgentArtifact.generated_at.desc()).first()

        if not md_artifact and not json_artifact:
            continue

        ctx = session.agent_context or {}
        if ctx.get("hidden_from_roster"):
            continue
        field = ctx.get("field") or (profile.field if profile else "Professional")
        job_title = ctx.get("current_job") or (profile.current_job if profile else None)
        industry = ctx.get("industry") or (profile.industry if profile else None)
        template = resolve_studio_for_field(field)
        total_tasks = len(template.get("tasks", []))
        completed_tasks = TaskResponse.query.filter_by(session_id=session.id).count()

        skills = []
        skill_source = ctx.get("skillset") or (profile.skillset if profile else "")
        if skill_source:
            skills = [s.strip() for s in skill_source.replace("\n", ",").split(",") if s.strip()]

        framework = _load_framework_summary(json_artifact) if json_artifact else None
        profile_text = _load_profile_preview(md_artifact) if md_artifact else None

        jd = dict(ctx.get("job_description") or {})
        job_description = jd if (
            jd.get("title") or jd.get("summary") or jd.get("responsibilities")
        ) else None
        if job_description and job_description.get("responsibilities"):
            job_description["responsibilities"] = list(job_description["responsibilities"])

        personas.append({
            "session_id": session.id,
            "name": ctx.get("full_name") or (profile.full_name if profile else "My Agent"),
            "field": field,
            "industry": industry,
            "job_title": job_title,
            "job_description": job_description,
            "icon": _persona_icon(field),
            "initials": _initials(ctx.get("full_name") or (profile.full_name if profile else None)),
            "studio_template": session.studio_template,
            "status": session.status,
            "training": {
                "completed": completed_tasks,
                "total": total_tasks,
            },
            "skills": skills,
            "framework": framework,
            "profile_preview": profile_text,
            "generated_at": session.agent_generated_at.isoformat() if session.agent_generated_at else None,
            "artifacts": {
                "profile_md_id": md_artifact.id if md_artifact else None,
                "framework_json_id": json_artifact.id if json_artifact else None,
                "skill_md_id": skill_artifact.id if skill_artifact else None,
            },
        })

    user_info = None
    if profile:
        user_info = {
            "full_name": profile.full_name,
            "email": current_user.email,
            "field": profile.field,
            "current_job": profile.current_job,
            "skillset": profile.skillset,
            "years_experience": profile.years_experience,
            "industry": profile.industry,
            "completed_background": profile.completed_background,
            "resume": {
                "has_resume": bool(profile.resume_file_path),
                "original_name": profile.resume_original_name,
                "uploaded_at": profile.resume_uploaded_at.isoformat() if profile.resume_uploaded_at else None,
                "download_url": "/api/profile/resume/download" if profile.resume_file_path else None,
                "view_url": "/api/profile/resume/view" if profile.resume_file_path else None,
            },
        }

    return jsonify({
        "user": user_info,
        "personas": personas,
    })
