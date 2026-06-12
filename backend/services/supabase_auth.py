"""Supabase Auth integration via REST API (no supabase-py dependency)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from flask import current_app, session

from backend.models import User, UserProfile, db

SUPABASE_MANAGED_PASSWORD = ""


@dataclass
class SupabaseAuthResult:
    supabase_user_id: str
    email: str
    access_token: str | None
    refresh_token: str | None
    email_confirmation_required: bool = False


def supabase_auth_enabled() -> bool:
    if current_app.config.get("DISABLE_AUTH"):
        return False
    return bool(
        current_app.config.get("SUPABASE_URL")
        and current_app.config.get("SUPABASE_ANON_KEY")
    )


def _auth_url(path: str) -> str:
    base = current_app.config["SUPABASE_URL"].rstrip("/")
    return f"{base}/auth/v1{path}"


def _request(
    method: str,
    path: str,
    *,
    body: dict | None = None,
    api_key: str | None = None,
    bearer: str | None = None,
) -> dict:
    key = api_key or current_app.config["SUPABASE_ANON_KEY"]
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {bearer or key}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(_auth_url(path), data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            msg = parsed.get("msg") or parsed.get("error_description") or parsed.get("message") or detail
        except json.JSONDecodeError:
            msg = detail or exc.reason
        raise ValueError(msg) from exc


def _normalize_uuid(value: str | uuid.UUID | None) -> str | None:
    if value is None:
        return None
    return str(value)


def store_session_tokens(access_token: str | None, refresh_token: str | None) -> None:
    session["supabase_access_token"] = access_token
    session["supabase_refresh_token"] = refresh_token


def clear_session_tokens() -> None:
    session.pop("supabase_access_token", None)
    session.pop("supabase_refresh_token", None)


def sync_local_user(supabase_user_id: str, email: str) -> User:
    """Link Supabase auth.users to the app users row (create profile if new)."""
    email = email.strip().lower()
    auth_id = _normalize_uuid(supabase_user_id)
    user = User.query.filter_by(supabase_auth_id=auth_id).first()
    if not user:
        user = User.query.filter_by(email=email).first()
    if user:
        user.email = email
        user.supabase_auth_id = auth_id
        if user.password_hash is None:
            user.password_hash = SUPABASE_MANAGED_PASSWORD
        if not user.profile:
            db.session.add(UserProfile(user_id=user.id))
        db.session.commit()
        return user

    user = User(
        email=email,
        supabase_auth_id=auth_id,
        password_hash=SUPABASE_MANAGED_PASSWORD,
    )
    db.session.add(user)
    db.session.flush()
    db.session.add(UserProfile(user_id=user.id))
    db.session.commit()
    return user


def sign_up(email: str, password: str) -> SupabaseAuthResult:
    payload = _request("POST", "/signup", body={
        "email": email.strip().lower(),
        "password": password,
    })
    user = payload.get("user") or {}
    user_email = (user.get("email") or email).lower()
    user_id = user.get("id")
    if not user_id:
        raise ValueError("Sign up failed — no user returned from Supabase.")

    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    confirmation_required = not access
    return SupabaseAuthResult(
        supabase_user_id=_normalize_uuid(user_id),
        email=user_email,
        access_token=access,
        refresh_token=refresh,
        email_confirmation_required=confirmation_required,
    )


def sign_in(email: str, password: str) -> SupabaseAuthResult:
    payload = _request("POST", "/token?grant_type=password", body={
        "email": email.strip().lower(),
        "password": password,
    })
    user = payload.get("user") or {}
    access = payload.get("access_token")
    if not access or not user.get("id"):
        raise ValueError("Invalid credentials.")

    return SupabaseAuthResult(
        supabase_user_id=_normalize_uuid(user["id"]),
        email=(user.get("email") or email).lower(),
        access_token=access,
        refresh_token=payload.get("refresh_token"),
    )


def sign_out() -> None:
    access_token = session.get("supabase_access_token")
    if access_token and supabase_auth_enabled():
        try:
            _request("POST", "/logout", bearer=access_token)
        except Exception:
            pass
    clear_session_tokens()


def reset_password_for_email(email: str, redirect_to: str) -> None:
    _request("POST", "/recover", body={
        "email": email.strip().lower(),
        "redirect_to": redirect_to,
    })


def ensure_supabase_user(email: str, password: str, *, email_confirm: bool = True) -> str | None:
    """Create a Supabase auth user via admin API (demo seeding). Returns auth user id."""
    service_key = current_app.config.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not service_key:
        return None
    normalized = email.strip().lower()
    try:
        payload = _request(
            "POST",
            "/admin/users",
            body={
                "email": normalized,
                "password": password,
                "email_confirm": email_confirm,
            },
            api_key=service_key,
            bearer=service_key,
        )
        user_id = (payload.get("id") or (payload.get("user") or {}).get("id"))
        if user_id:
            return _normalize_uuid(user_id)
    except Exception as exc:
        if "already" not in str(exc).lower() and "exists" not in str(exc).lower():
            raise

    page = 1
    while page <= 10:
        listing = _request(
            "GET",
            f"/admin/users?page={page}&per_page=200",
            api_key=service_key,
            bearer=service_key,
        )
        users = listing.get("users") if isinstance(listing, dict) else listing
        if not isinstance(users, list):
            break
        for u in users:
            if (u.get("email") or "").lower() == normalized:
                return _normalize_uuid(u.get("id"))
        if len(users) < 200:
            break
        page += 1
    return None
