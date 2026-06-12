from flask import Blueprint, current_app, g, jsonify, request
from flask_login import login_user, logout_user, login_required, current_user

from backend.models import User, UserProfile, db
from backend.services.dev_auth import DEMO_EMAIL, login_demo_user
from backend.services.event_logger import log_event
from backend.services.supabase_auth import (
    clear_session_tokens,
    reset_password_for_email,
    sign_in as supabase_sign_in,
    sign_out as supabase_sign_out,
    sign_up as supabase_sign_up,
    store_session_tokens,
    supabase_auth_enabled,
    sync_local_user,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _login_local_user(user: User) -> None:
    login_user(user)
    g.current_user_id = user.id


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    if User.query.filter_by(email=email).first() and not supabase_auth_enabled():
        return jsonify({"error": "Email already registered"}), 409

    if supabase_auth_enabled():
        try:
            result = supabase_sign_up(email, password)
        except Exception as exc:
            msg = str(exc).lower()
            if "already" in msg or "registered" in msg or "exists" in msg:
                return jsonify({"error": "Email already registered"}), 409
            return jsonify({"error": "Could not create account. Try again or log in."}), 400

        if result.email_confirmation_required:
            return jsonify({
                "email": result.email,
                "message": "Check your email to confirm your account, then log in.",
                "email_confirmation_required": True,
            }), 201

        user = sync_local_user(result.supabase_user_id, result.email)
        store_session_tokens(result.access_token, result.refresh_token)
        _login_local_user(user)
        log_event("user_registered", {"email": email, "auth": "supabase"})
        return jsonify({"id": user.id, "email": user.email}), 201

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 409

    user = User(email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    db.session.add(UserProfile(user_id=user.id))
    db.session.commit()

    _login_local_user(user)
    log_event("user_registered", {"email": email, "auth": "local"})
    return jsonify({"id": user.id, "email": user.email}), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    if current_app.config.get("DISABLE_AUTH"):
        user = login_demo_user()
        g.current_user_id = user.id
        log_event("user_logged_in", {"email": user.email, "dev_bypass": True})
        return jsonify({"id": user.id, "email": user.email})

    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    if supabase_auth_enabled():
        try:
            result = supabase_sign_in(email, password)
        except Exception:
            return jsonify({
                "error": "Invalid credentials. Check your email and password, or confirm your email if you just signed up.",
            }), 401

        user = sync_local_user(result.supabase_user_id, result.email)
        store_session_tokens(result.access_token, result.refresh_token)
        _login_local_user(user)
        log_event("user_logged_in", {"email": email, "auth": "supabase"})
        return jsonify({"id": user.id, "email": user.email})

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        if email == DEMO_EMAIL:
            return jsonify({
                "error": "Invalid credentials. Try password: demo, or register a new account.",
            }), 401
        return jsonify({
            "error": "Invalid credentials. Check your email and password, or create an account.",
        }), 401

    _login_local_user(user)
    log_event("user_logged_in", {"email": email, "auth": "local"})
    return jsonify({"id": user.id, "email": user.email})


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    log_event("user_logged_out")
    supabase_sign_out()
    logout_user()
    return jsonify({"ok": True})


@auth_bp.route("/forgot-password", methods=["POST"])
def forgot_password():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "Email is required"}), 400

    if supabase_auth_enabled():
        try:
            redirect_to = f"{current_app.config.get('APP_URL', 'http://localhost:5000')}/#login"
            reset_password_for_email(email, redirect_to)
        except Exception:
            pass

    return jsonify({
        "ok": True,
        "message": "If an account exists for that email, a reset link has been sent.",
    })


@auth_bp.route("/me", methods=["GET"])
@login_required
def me():
    g.current_user_id = current_user.id
    profile = current_user.profile
    return jsonify({
        "id": current_user.id,
        "email": current_user.email,
        "subscription_status": current_user.subscription_status,
        "auth_provider": "supabase" if current_user.uses_supabase_auth else "local",
        "profile": {
            "full_name": profile.full_name if profile else None,
            "field": profile.field if profile else None,
            "skillset": profile.skillset if profile else None,
            "current_job": profile.current_job if profile else None,
            "years_experience": profile.years_experience if profile else None,
            "industry": profile.industry if profile else None,
            "completed_background": profile.completed_background if profile else False,
            "has_resume": bool(profile.resume_file_path) if profile else False,
            "resume_original_name": profile.resume_original_name if profile else None,
        } if profile else None,
    })
