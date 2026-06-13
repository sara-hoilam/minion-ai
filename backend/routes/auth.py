from flask import Blueprint, current_app, g, jsonify, request
from flask_login import login_user, logout_user, login_required, current_user

from backend.models import User, UserProfile, db
from backend.services.dev_auth import DEMO_EMAIL, login_demo_user
from backend.services.event_logger import log_event
from backend.services.profile_names import apply_profile_names, normalize_name_part, profile_name_parts
from backend.services.supabase_auth import (
    auth_user_exists,
    clear_session_tokens,
    find_supabase_auth_user,
    get_user_from_token,
    is_supabase_email_confirmed,
    resend_signup_confirmation,
    reset_password_for_email,
    sign_in as supabase_sign_in,
    sign_out as supabase_sign_out,
    sign_up as supabase_sign_up,
    store_session_tokens,
    supabase_auth_enabled,
    sync_local_user,
    update_password,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _login_local_user(user: User) -> None:
    login_user(user)
    g.current_user_id = user.id


def _profile_payload(profile: UserProfile | None) -> dict | None:
    if not profile:
        return None
    first, last = profile_name_parts(profile)
    return {
        "first_name": first or None,
        "last_name": last or None,
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


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    first_name = normalize_name_part(data.get("first_name"))
    last_name = normalize_name_part(data.get("last_name"))

    password_confirm = data.get("password_confirm") or ""

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400
    if not first_name or not last_name:
        return jsonify({"error": "First name and last name are required"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    if password_confirm and password != password_confirm:
        return jsonify({"error": "Passwords do not match"}), 400

    if User.query.filter_by(email=email).first() and not supabase_auth_enabled():
        return jsonify({"error": "Email already registered"}), 409

    if supabase_auth_enabled():
        existing = find_supabase_auth_user(email)
        if existing:
            if not is_supabase_email_confirmed(existing):
                try:
                    resend_signup_confirmation(email)
                    resent = True
                except Exception:
                    resent = False
                message = (
                    "An account with this email already exists but isn't confirmed yet. "
                    + ("We sent another confirmation email — check your inbox (and spam)." if resent else "Check your inbox for the confirmation link.")
                )
                return jsonify({
                    "error": message,
                    "email_confirmation_required": True,
                }), 409
            return jsonify({"error": "Email already registered. Log in instead."}), 409

        try:
            result = supabase_sign_up(email, password, first_name=first_name, last_name=last_name)
        except Exception as exc:
            msg = str(exc).lower()
            if "already" in msg or "registered" in msg or "exists" in msg:
                return jsonify({"error": "Email already registered. Log in instead."}), 409
            return jsonify({"error": "Could not create account. Try again or log in."}), 400

        if result.email_confirmation_required:
            return jsonify({
                "email": result.email,
                "message": "Check your email to confirm your account, then log in.",
                "email_confirmation_required": True,
            }), 201

        user = sync_local_user(
            result.supabase_user_id,
            result.email,
            first_name=first_name,
            last_name=last_name,
        )
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
    profile = UserProfile(user_id=user.id)
    apply_profile_names(profile, first_name, last_name)
    db.session.add(profile)
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
            existing = find_supabase_auth_user(email)
            if existing and not is_supabase_email_confirmed(existing):
                return jsonify({
                    "error": "Please confirm your email before signing in. Check your inbox (and spam) for the confirmation link.",
                    "email_confirmation_required": True,
                }), 403
            if not auth_user_exists(email):
                return jsonify({
                    "error": "No account found for this email.",
                    "redirect": "register",
                    "email": email,
                }), 404
            return jsonify({
                "error": "Invalid credentials. Check your email and password.",
            }), 401

        user = sync_local_user(result.supabase_user_id, result.email)
        store_session_tokens(result.access_token, result.refresh_token)
        _login_local_user(user)
        log_event("user_logged_in", {"email": email, "auth": "supabase"})
        return jsonify({"id": user.id, "email": user.email})

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({
            "error": "No account found for this email.",
            "redirect": "register",
            "email": email,
        }), 404
    if not user.check_password(password):
        if email == DEMO_EMAIL:
            return jsonify({
                "error": "Invalid credentials. Try password: demo, or register a new account.",
            }), 401
        return jsonify({
            "error": "Invalid credentials. Check your email and password.",
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
            app_url = current_app.config.get("APP_URL", "http://localhost:5000").rstrip("/")
            redirect_to = f"{app_url}/#reset-password"
            reset_password_for_email(email, redirect_to)
            log_event("password_reset_requested", {"email": email, "auth": "supabase"})
        except Exception:
            pass

    return jsonify({
        "ok": True,
        "message": "If an account exists for that email, a reset link has been sent.",
    })


@auth_bp.route("/reset-password", methods=["POST"])
def reset_password():
    data = request.get_json() or {}
    password = data.get("password") or ""
    password_confirm = data.get("password_confirm") or ""
    access_token = (data.get("access_token") or "").strip()
    refresh_token = (data.get("refresh_token") or "").strip() or None

    if not password or not password_confirm:
        return jsonify({"error": "Password and confirmation are required"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    if password != password_confirm:
        return jsonify({"error": "Passwords do not match"}), 400
    if not access_token:
        return jsonify({"error": "Invalid or expired reset link. Request a new one."}), 400

    if not supabase_auth_enabled():
        return jsonify({"error": "Password reset is not available."}), 400

    try:
        update_password(access_token, password)
        user_payload = get_user_from_token(access_token)
        supabase_user_id = user_payload.get("id")
        user_email = (user_payload.get("email") or "").strip().lower()
        if not supabase_user_id or not user_email:
            return jsonify({"error": "Could not complete password reset."}), 400

        user = sync_local_user(supabase_user_id, user_email)
        store_session_tokens(access_token, refresh_token)
        _login_local_user(user)
        log_event("password_reset_completed", {"email": user_email, "auth": "supabase"})
        return jsonify({"id": user.id, "email": user.email})
    except Exception:
        return jsonify({
            "error": "Could not reset password. The link may have expired — request a new reset email.",
        }), 400


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
        "profile": _profile_payload(profile),
    })
