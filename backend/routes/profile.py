from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, g, jsonify, request, send_file
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from backend.config import UPLOAD_FOLDER
from backend.models import db
from backend.services.event_logger import log_event
from backend.services.field_catalog import catalog_payload
from backend.services.resume_parser import parse_resume

profile_bp = Blueprint("profile", __name__, url_prefix="/api/profile")

ALLOWED_RESUME_EXTENSIONS = {".pdf", ".docx", ".html", ".htm"}


@profile_bp.route("/catalog", methods=["GET"])
def get_catalog():
    return jsonify(catalog_payload())


@profile_bp.route("/background", methods=["POST"])
@login_required
def save_background():
    return _save_profile(request.get_json() or {}, mark_completed=True)


@profile_bp.route("", methods=["PUT"])
@login_required
def update_profile():
    return _save_profile(request.get_json() or {}, mark_completed=False)


def _save_profile(data: dict, mark_completed: bool):
    profile = current_user.profile
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    if "full_name" in data:
        profile.full_name = data.get("full_name")
    if "field" in data:
        profile.field = data.get("field")
    if "skillset" in data:
        profile.skillset = data.get("skillset")
    if "current_job" in data:
        profile.current_job = data.get("current_job")
    if "years_experience" in data:
        profile.years_experience = data.get("years_experience")
    if "industry" in data:
        profile.industry = data.get("industry")
    if mark_completed or profile.completed_background:
        profile.completed_background = True

    db.session.commit()
    g.current_user_id = current_user.id
    log_event(
        "background_completed" if mark_completed else "profile_updated",
        {"field": profile.field, "current_job": profile.current_job},
    )

    return jsonify({"ok": True, "profile": _profile_dict(profile)})


@profile_bp.route("/resume", methods=["POST"])
@login_required
def upload_resume():
    if "resume" not in request.files:
        return jsonify({"error": "No resume file provided"}), 400

    file = request.files["resume"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_RESUME_EXTENSIONS:
        return jsonify({"error": "Upload PDF, Word (.docx), or HTML"}), 400

    profile = current_user.profile
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    data = file.read()
    if len(data) > 10 * 1024 * 1024:
        return jsonify({"error": "File too large (max 10 MB)"}), 400

    try:
        parsed = parse_resume(file.filename, data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Resume parse failed")
        return jsonify({"error": f"Could not read resume file: {exc}"}), 422

    user_dir = UPLOAD_FOLDER / "resumes" / str(current_user.id)
    user_dir.mkdir(parents=True, exist_ok=True)

    if profile.resume_file_path:
        old_path = Path(profile.resume_file_path)
        if old_path.exists():
            old_path.unlink()

    safe_name = secure_filename(file.filename)
    stored_name = f"{uuid4().hex}_{safe_name}"
    file_path = user_dir / stored_name
    file_path.write_bytes(data)

    profile.resume_file_path = str(file_path)
    profile.resume_original_name = file.filename
    profile.resume_uploaded_at = datetime.now(timezone.utc)

    if parsed.get("full_name"):
        profile.full_name = parsed["full_name"]
    if parsed.get("field"):
        profile.field = parsed["field"]
    if parsed.get("skillset"):
        profile.skillset = parsed["skillset"]
    if parsed.get("current_job"):
        profile.current_job = parsed["current_job"]
    if parsed.get("years_experience") is not None:
        profile.years_experience = parsed["years_experience"]
    if parsed.get("industry"):
        profile.industry = parsed["industry"]

    db.session.commit()
    g.current_user_id = current_user.id
    log_event("resume_uploaded", {
        "filename": file.filename,
        "fields_extracted": [k for k, v in parsed.items() if v and k != "raw_text_preview"],
    })

    return jsonify({
        "ok": True,
        "autofill": {
            "full_name": profile.full_name,
            "field": profile.field,
            "skillset": profile.skillset,
            "current_job": profile.current_job,
            "years_experience": profile.years_experience,
            "industry": profile.industry,
        },
        "resume": {
            "original_name": profile.resume_original_name,
            "uploaded_at": profile.resume_uploaded_at.isoformat() if profile.resume_uploaded_at else None,
        },
    })


@profile_bp.route("/resume", methods=["GET"])
@login_required
def get_resume_info():
    profile = current_user.profile
    if not profile or not profile.resume_file_path:
        return jsonify({"has_resume": False})

    return jsonify({
        "has_resume": True,
        "original_name": profile.resume_original_name,
        "uploaded_at": profile.resume_uploaded_at.isoformat() if profile.resume_uploaded_at else None,
        "download_url": "/api/profile/resume/download",
        "view_url": "/api/profile/resume/view",
    })


@profile_bp.route("/resume/view", methods=["GET"])
@login_required
def view_resume():
    profile = current_user.profile
    if not profile or not profile.resume_file_path:
        return jsonify({"error": "No resume on file"}), 404

    path = Path(profile.resume_file_path)
    if not path.exists():
        return jsonify({"error": "Resume file missing"}), 404

    ext = path.suffix.lower()
    mimetypes = {
        ".pdf": "application/pdf",
        ".html": "text/html",
        ".htm": "text/html",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    mimetype = mimetypes.get(ext, "application/octet-stream")
    return send_file(
        path,
        mimetype=mimetype,
        as_attachment=False,
        download_name=profile.resume_original_name or path.name,
    )


@profile_bp.route("/resume", methods=["DELETE"])
@login_required
def delete_resume():
    profile = current_user.profile
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    if profile.resume_file_path:
        path = Path(profile.resume_file_path)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass

    profile.resume_file_path = None
    profile.resume_original_name = None
    profile.resume_uploaded_at = None
    db.session.commit()

    g.current_user_id = current_user.id
    log_event("resume_deleted", {})

    return jsonify({"ok": True})


@profile_bp.route("/resume/download", methods=["GET"])
@login_required
def download_resume():
    profile = current_user.profile
    if not profile or not profile.resume_file_path:
        return jsonify({"error": "No resume on file"}), 404

    path = Path(profile.resume_file_path)
    if not path.exists():
        return jsonify({"error": "Resume file missing"}), 404

    return send_file(
        path,
        as_attachment=True,
        download_name=profile.resume_original_name or path.name,
    )


def _profile_dict(profile) -> dict:
    return {
        "full_name": profile.full_name,
        "field": profile.field,
        "skillset": profile.skillset,
        "current_job": profile.current_job,
        "years_experience": profile.years_experience,
        "industry": profile.industry,
        "completed_background": profile.completed_background,
        "has_resume": bool(profile.resume_file_path),
        "resume_original_name": profile.resume_original_name,
    }
