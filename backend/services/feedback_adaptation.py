"""Apply approved agent feedback into agent context."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.models import AgentFeedback, StudioSession, db

MAX_DIGEST_ENTRIES = 20


def apply_feedback_to_session(
    session: StudioSession,
    content: str,
    *,
    project_id: int | None = None,
) -> None:
    ctx = dict(session.agent_context or {})
    digest = list(ctx.get("feedback_digest") or [])
    digest.append({
        "content": content.strip(),
        "project_id": project_id,
        "applied_at": datetime.now(timezone.utc).isoformat(),
    })
    ctx["feedback_digest"] = digest[-MAX_DIGEST_ENTRIES:]

    bullets = [f"- {d['content']}" for d in ctx["feedback_digest"][-10:]]
    ctx["working_instructions"] = (
        "Incorporate this user feedback about your output quality and reasoning:\n"
        + "\n".join(bullets)
    )

    session.agent_context = ctx


def apply_approved_feedback(feedback: AgentFeedback) -> None:
    session = db.session.get(StudioSession, feedback.agent_session_id)
    if not session:
        return

    apply_feedback_to_session(
        session,
        feedback.content,
        project_id=feedback.project_id,
    )
    feedback.applied_at = datetime.now(timezone.utc)
    db.session.commit()


def format_feedback_digest(agent_context: dict) -> str:
    digest = agent_context.get("feedback_digest") or []
    if not digest:
        wi = agent_context.get("working_instructions")
        return wi.strip() if wi else ""
    lines = ["User feedback to apply (approved):"]
    for entry in digest[-10:]:
        lines.append(f"- {entry.get('content', '')}")
    wi = agent_context.get("working_instructions")
    if wi and wi not in lines[-1]:
        lines.append("")
        lines.append(wi)
    return "\n".join(lines)[:4000]
