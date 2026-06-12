"""Platform-wide defaults applied to every agent."""

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


def today_label() -> str:
    """Human-readable local date for LLM temporal context."""
    return date.today().strftime("%A, %B %d, %Y")


def temporal_context_line() -> str:
    return f"Today is {today_label()}."


def _parse_skillset(skillset: str | None) -> list[str]:
    if not skillset:
        return []
    return [s.strip() for s in skillset.replace("\n", ",").split(",") if s.strip()]


def ensure_platform_skills_in_skillset(skillset: str | None) -> str:
    skills = _parse_skillset(skillset)
    for platform_skill in reversed(PLATFORM_SKILLS):
        if not any(s.lower() == platform_skill.lower() for s in skills):
            skills.insert(0, platform_skill)
    return ", ".join(skills)


def ensure_first_principles_in_skillset(skillset: str | None) -> str:
    return ensure_platform_skills_in_skillset(skillset)


def working_instructions_include_first_principles(text: str | None) -> bool:
    return "first principles" in (text or "").lower()


def working_instructions_include_data_freshness(text: str | None) -> bool:
    lowered = (text or "").lower()
    return "latest available data" in lowered or "current data awareness" in lowered


def _default_instruction_blocks(user_text: str | None) -> list[str]:
    user = (user_text or "").strip()
    blocks: list[str] = []
    if not working_instructions_include_first_principles(user):
        blocks.append(FIRST_PRINCIPLES_INSTRUCTIONS)
    if not working_instructions_include_data_freshness(user):
        blocks.append(DATA_FRESHNESS_INSTRUCTIONS)
    return blocks


def merge_working_instructions(user_text: str | None) -> str:
    """Default standing instructions for newly created agents."""
    user = (user_text or "").strip()
    defaults = "\n\n".join(_default_instruction_blocks(user))
    if not defaults:
        return user
    if user:
        return f"{defaults}\n\n{user}"
    return defaults


def first_principles_instruction_block(agent_context: dict | None) -> str:
    """Runtime block for agents that predate the default instructions."""
    ctx = agent_context or {}
    if working_instructions_include_first_principles(ctx.get("working_instructions")):
        return ""
    return FIRST_PRINCIPLES_INSTRUCTIONS


def data_freshness_instruction_block(agent_context: dict | None) -> str:
    """Runtime data-currency guidance for agents missing standing instructions."""
    ctx = agent_context or {}
    if working_instructions_include_data_freshness(ctx.get("working_instructions")):
        return ""
    return DATA_FRESHNESS_INSTRUCTIONS


def enrich_agent_context(context: dict) -> dict:
    """Apply platform defaults when an agent is created or restored."""
    enriched = dict(context)
    enriched["skillset"] = ensure_platform_skills_in_skillset(enriched.get("skillset"))
    enriched["working_instructions"] = merge_working_instructions(
        enriched.get("working_instructions"),
    )
    return enriched
