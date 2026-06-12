"""Dev-mode auth bypass for local testing."""

from flask import current_app
from flask_login import login_user, current_user

from backend.models import User, UserProfile, db
from backend.services.supabase_auth import (
    ensure_supabase_user,
    supabase_auth_enabled,
    sync_local_user,
)


DEMO_EMAIL = "demo@minion.ai"
DEMO_PASSWORD = "demo"


def ensure_demo_user() -> User:
    if supabase_auth_enabled() and current_app.config.get("SUPABASE_SERVICE_ROLE_KEY"):
        try:
            auth_id = ensure_supabase_user(DEMO_EMAIL, DEMO_PASSWORD, email_confirm=True)
            if auth_id:
                return sync_local_user(auth_id, DEMO_EMAIL)
        except Exception:
            pass

    user = User.query.filter_by(email=DEMO_EMAIL).first()
    if not user:
        user = User(email=DEMO_EMAIL)
        user.set_password(DEMO_PASSWORD)
        db.session.add(user)
        db.session.flush()
        db.session.add(UserProfile(user_id=user.id))
        db.session.commit()
    elif not user.profile:
        db.session.add(UserProfile(user_id=user.id))
        db.session.commit()
    return user


def login_demo_user() -> User:
    user = ensure_demo_user()
    login_user(user)
    return user


def auto_login_if_disabled() -> None:
    if not current_app.config.get("DISABLE_AUTH"):
        return
    if not current_user.is_authenticated:
        login_user(ensure_demo_user())


def seed_demo_user_on_startup() -> None:
    """Ensure the local demo account exists whenever the app starts."""
    ensure_demo_user()
