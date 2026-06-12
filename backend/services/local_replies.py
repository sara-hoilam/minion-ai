"""Instant replies for trivial prompts — no Cursor API round-trip."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from backend.services.thinking_principles import today_label

_GREETINGS = frozenset({
    "hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "yo", "good morning",
    "good afternoon", "good evening",
})

_DATE_PATTERNS = (
    r"\bwhat(?:'s| is) the date\b",
    r"\bwhat date\b",
    r"\bwhat(?:'s| is) the time\b",
    r"\bwhat time\b",
    r"\bwhat day is\b",
    r"\btoday(?:'s)? date\b",
    r"\bcurrent date\b",
    r"\bwhat day is it\b",
)

_TIME_PATTERNS = (
    r"\bwhat(?:'s| is) the time\b",
    r"\bwhat time is it\b",
    r"\bcurrent time\b",
)


def normalize_user_query(user_message: str) -> str:
    text = (user_message or "").strip()
    text = re.sub(r"^@[^\s]+\s+", "", text, flags=re.IGNORECASE)
    return text.strip()


def _looks_date_question(lower: str) -> bool:
    return any(re.search(pat, lower) for pat in _DATE_PATTERNS)


def _looks_time_question(lower: str) -> bool:
    return any(re.search(pat, lower) for pat in _TIME_PATTERNS)


def _looks_greeting(lower: str) -> bool:
    normalized = re.sub(r"[^\w\s]", "", lower).strip()
    if normalized in _GREETINGS:
        return True
    return any(normalized.startswith(g + " ") for g in ("hi", "hello", "hey", "good morning", "good afternoon", "good evening"))


def try_instant_reply(user_message: str, agent_name: str) -> str | None:
    """Return a local answer when LLM latency is unnecessary."""
    text = normalize_user_query(user_message)
    if not text:
        return None
    lower = text.lower()

    if _looks_date_question(lower):
        return f"Today is {today_label()}."

    if _looks_time_question(lower):
        now = datetime.now(timezone.utc).astimezone()
        return f"It's {now.strftime('%I:%M %p %Z')} ({today_label()})."

    if _looks_greeting(lower) and len(lower.split()) <= 8:
        first = (agent_name or "Agent").split()[0]
        return f"Hi! I'm {agent_name}. Good to hear from you — what would you like to work on?"

    if re.search(r"\bwho are you\b", lower):
        return (
            f"I'm {agent_name}, your AI agent on Minion AI. "
            f"I can help with analysis, planning, and specialist workflows in my domain."
        )

    if re.search(r"\bwhat can you do\b", lower):
        return (
            f"I'm {agent_name}. I can answer questions, analyze problems, and coordinate "
            f"specialist skills for deeper work. Tell me what you're trying to accomplish."
        )

    return None
