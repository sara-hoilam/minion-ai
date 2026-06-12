from flask import Blueprint, g, jsonify, request
from flask_login import login_required, current_user

from backend.models import Event
from backend.services.event_logger import log_event

events_bp = Blueprint("events", __name__, url_prefix="/api/events")


@events_bp.route("", methods=["POST"])
@login_required
def track_client_event():
    data = request.get_json() or {}
    event_type = data.get("event_type")
    if not event_type:
        return jsonify({"error": "event_type required"}), 400

    g.current_user_id = current_user.id
    log_event(event_type, data.get("payload", {}), session_id=data.get("session_id"))
    return jsonify({"ok": True})


@events_bp.route("/funnel", methods=["GET"])
@login_required
def onboarding_funnel():
    """Aggregate onboarding/studio funnel for the current user (admin view in v1)."""
    user_events = Event.query.filter_by(user_id=current_user.id).order_by(Event.created_at).all()
    return jsonify([
        {"event_type": e.event_type, "payload": e.payload, "created_at": e.created_at.isoformat()}
        for e in user_events
    ])
