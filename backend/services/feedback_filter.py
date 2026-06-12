"""Filter project-panel feedback before agent adaptation."""

from __future__ import annotations

import json
import re

from backend.services.cursor_llm import complete as cursor_complete
from backend.services.cursor_llm import is_configured as cursor_configured

PROFANITY_RE = re.compile(r"\b(shit|fuck|damn)\b", re.I)
APPROVAL_THRESHOLD = 0.65


def _rule_based_filter(content: str, agent_context: dict) -> dict:
    text = (content or "").strip()
    if len(text) < 10:
        return {
            "is_constructive": False,
            "is_relevant": False,
            "categories": ["off_topic"],
            "score": 0.1,
            "reason": "Feedback is too short to be actionable.",
        }
    if PROFANITY_RE.search(text) and len(text.split()) < 6:
        return {
            "is_constructive": False,
            "is_relevant": False,
            "categories": ["off_topic"],
            "score": 0.0,
            "reason": "Feedback was not constructive.",
        }
    skills = agent_context.get("skillset") or agent_context.get("field") or "general work"
    actionable = any(w in text.lower() for w in (
        "should", "please", "more", "less", "better", "improve", "avoid", "focus",
        "concise", "detail", "accuracy", "format", "tone", "reasoning", "summary",
    ))
    score = 0.75 if actionable else 0.45
    return {
        "is_constructive": actionable,
        "is_relevant": actionable,
        "categories": ["output_quality"] if actionable else ["off_topic"],
        "score": score,
        "reason": "Approved for agent improvement." if actionable else "Feedback was too vague.",
    }


def classify_feedback(
    content: str,
    agent_context: dict,
    *,
    project_name: str | None = None,
    project_instructions: str | None = None,
    recent_assistant_snippet: str | None = None,
) -> dict:
    text = (content or "").strip()
    if len(text) < 10:
        return _rule_based_filter(text, agent_context)

    if not cursor_configured():
        return _rule_based_filter(text, agent_context)

    try:
        return _ai_classify_feedback(
            text,
            agent_context,
            project_name=project_name,
            project_instructions=project_instructions,
            recent_assistant_snippet=recent_assistant_snippet,
        )
    except Exception:
        return _rule_based_filter(text, agent_context)


def _ai_classify_feedback(
    text: str,
    agent_context: dict,
    *,
    project_name: str | None = None,
    project_instructions: str | None = None,
    recent_assistant_snippet: str | None = None,
) -> dict:
    agent_name = agent_context.get("full_name") or "Agent"
    skills = agent_context.get("skillset") or agent_context.get("field") or ""
    job = agent_context.get("current_job") or ""

    system = (
        "You classify user feedback about an AI agent. Respond with JSON only:\n"
        '{"is_constructive": bool, "is_relevant": bool, "categories": [str], "score": float, "reason": str}\n'
        "Approve only feedback that is specific, actionable, and about the agent's skills, reasoning, tone, "
        "accuracy, or output quality. Reject spam, abuse, off-topic, or vague praise/complaints."
    )
    user_parts = [
        f"Agent: {agent_name}",
        f"Role: {job}",
        f"Skills: {skills}",
    ]
    if project_name:
        user_parts.append(f"Project: {project_name}")
    if project_instructions:
        user_parts.append(f"Project instructions: {project_instructions[:500]}")
    if recent_assistant_snippet:
        user_parts.append(f"Recent agent output snippet: {recent_assistant_snippet[:800]}")
    user_parts.append(f"User feedback:\n{text}")

    raw = cursor_complete(system, "\n\n".join(user_parts))
    if not raw:
        return _rule_based_filter(text, agent_context)

    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        parsed = json.loads(raw[start:end]) if start >= 0 else {}
    except json.JSONDecodeError:
        return _rule_based_filter(text, agent_context)

    score = float(parsed.get("score", 0))
    is_constructive = bool(parsed.get("is_constructive"))
    is_relevant = bool(parsed.get("is_relevant"))
    approved = score >= APPROVAL_THRESHOLD and is_constructive and is_relevant

    return {
        "is_constructive": is_constructive,
        "is_relevant": is_relevant,
        "categories": parsed.get("categories") or [],
        "score": score,
        "reason": parsed.get("reason") or ("Approved for agent improvement." if approved else "Not applicable."),
        "approved": approved,
    }


def feedback_status_from_classification(result: dict) -> str:
    if result.get("approved") or (
        result.get("score", 0) >= APPROVAL_THRESHOLD
        and result.get("is_constructive")
        and result.get("is_relevant")
    ):
        return "approved"
    return "filtered_out"
