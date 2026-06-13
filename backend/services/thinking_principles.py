"""Platform-wide defaults applied to every agent (prompt-only — not user-visible skills)."""

from __future__ import annotations

from datetime import date

FIRST_PRINCIPLES_SKILL = "First principles thinking"
CURRENT_DATA_SKILL = "Current data awareness"

FIRST_PRINCIPLES_INSTRUCTIONS = """Apply first principles thinking on every task:
- Break problems down to fundamental facts and constraints before proposing solutions
- Question assumptions; separate what is known from what is inferred
- Reason from basics upward rather than relying on analogy or convention alone
- State your premises explicitly, then derive conclusions step by step
- Prefer simple, explainable solutions built from verified truths"""

DATA_FRESHNESS_INSTRUCTIONS = """Use the latest available data when possible:
- Prefer the most recent data sources, metrics, and references available to you
- Use today's date when judging recency, time ranges, and "current" conditions
- State the as-of date for any figures, benchmarks, or market context you cite
- If you cannot access live data, say so explicitly and use the newest reliable alternative
- Flag when information may be outdated and what would be needed to refresh it"""

PLATFORM_SKILLS = (FIRST_PRINCIPLES_SKILL, CURRENT_DATA_SKILL)
_PLATFORM_SKILL_KEYS = {s.lower() for s in PLATFORM_SKILLS}


def today_label() -> str:
    """Human-readable local date for LLM temporal context."""
    return date.today().strftime("%A, %B %d, %Y")


def temporal_context_line() -> str:
    return f"Today is {today_label()}."


def _parse_skillset(skillset: str | None) -> list[str]:
    if not skillset:
        return []
    return [s.strip() for s in skillset.replace("\n", ",").split(",") if s.strip()]


def is_platform_skill(skill: str | None) -> bool:
    return (skill or "").strip().lower() in _PLATFORM_SKILL_KEYS


def user_skills_list(skillset: str | None) -> list[str]:
    """User-selected skills only (excludes platform defaults)."""
    return [s for s in _parse_skillset(skillset) if not is_platform_skill(s)]


def user_skillset(skillset: str | None, max_skills: int = 8) -> str:
    """Comma-separated user skills capped at max_skills."""
    return ", ".join(user_skills_list(skillset)[:max_skills])


def ensure_platform_skills_in_skillset(skillset: str | None) -> str:
    """Legacy helper — prefer user_skillset for storage; platform skills belong in prompts."""
    return user_skillset(skillset)


def ensure_first_principles_in_skillset(skillset: str | None) -> str:
    return ensure_platform_skills_in_skillset(skillset)


def strip_platform_instruction_blocks(text: str | None) -> str:
    """Remove auto-injected platform instruction blocks from user-visible text."""
    user = (text or "").strip()
    for block in (FIRST_PRINCIPLES_INSTRUCTIONS, DATA_FRESHNESS_INSTRUCTIONS):
        user = user.replace(block, "").strip()
    while "\n\n\n" in user:
        user = user.replace("\n\n\n", "\n\n")
    return user.strip()


def enrich_agent_context(context: dict) -> dict:
    """Normalize stored agent context — user skills only, no platform defaults in skillset."""
    enriched = dict(context)
    enriched["skillset"] = user_skillset(enriched.get("skillset"))
    if enriched.get("working_instructions"):
        cleaned = strip_platform_instruction_blocks(enriched["working_instructions"])
        enriched["working_instructions"] = cleaned or None
    return enriched


def first_principles_instruction_block(agent_context: dict | None) -> str:
    """Runtime prompt block (always applied via agent_instructions)."""
    return FIRST_PRINCIPLES_INSTRUCTIONS


def data_freshness_instruction_block(agent_context: dict | None) -> str:
    """Runtime prompt block (always applied via agent_instructions)."""
    return DATA_FRESHNESS_INSTRUCTIONS
