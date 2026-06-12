from flask import g, request

from backend.models import Event, db


def log_event(event_type: str, payload: dict | None = None, user_id: int | None = None, session_id: str | None = None) -> None:
    uid = user_id
    if uid is None and hasattr(g, "current_user_id"):
        uid = g.current_user_id

    event = Event(
        user_id=uid,
        session_id=session_id or request.headers.get("X-Session-Id"),
        event_type=event_type,
        payload=payload or {},
    )
    db.session.add(event)
    db.session.commit()
