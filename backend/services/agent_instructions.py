"""Agent settings block — always injected into LLM calls for task execution."""

from __future__ import annotations

from backend.services.thinking_principles import (
    DATA_FRESHNESS_INSTRUCTIONS,
    FIRST_PRINCIPLES_INSTRUCTIONS,
    temporal_context_line,
    user_skillset,
)


def build_agent_instruction_block(agent_context: dict | None) -> str:
    """
    User-authored agent settings from AI agent configuration.
    Platform reasoning defaults are appended here — never stored as user skills/instructions.
    """
    ctx = agent_context or {}
    parts: list[str] = [f"Temporal context: {temporal_context_line()}"]

    name = ctx.get("full_name") or "Agent"
    role_bits = [b for b in (ctx.get("current_job"), ctx.get("field"), ctx.get("industry")) if b]
    if role_bits:
        parts.append(f"Agent profile: {name} — {', '.join(role_bits)}.")
    else:
        parts.append(f"Agent profile: {name}.")

    skills = user_skillset(ctx.get("skillset"))
    if skills:
        parts.append(f"Core skillset: {skills}.")

    jd = ctx.get("job_description") or {}
    if jd.get("title"):
        parts.append(f"Role title: {jd['title']}.")
    if jd.get("summary"):
        parts.append(f"Role summary: {jd['summary']}")

    responsibilities = jd.get("responsibilities") or []
    if responsibilities:
        resp = "; ".join(str(r) for r in responsibilities[:6])
        parts.append(f"Key responsibilities: {resp}.")

    style = (ctx.get("communication_style") or "").strip()
    if style:
        parts.append(
            f"Communication style: {style}. Match this tone and level of detail in every reply."
        )

    instructions = (ctx.get("working_instructions") or "").strip()
    if instructions:
        parts.append(f"Standing instructions (always follow):\n{instructions}")

    parts.append(f"Core reasoning approach (always follow):\n{FIRST_PRINCIPLES_INSTRUCTIONS}")
    parts.append(f"Data currency (always follow):\n{DATA_FRESHNESS_INSTRUCTIONS}")

    if not parts:
        return ""

    return "AGENT SETTINGS (mandatory — apply on every task):\n" + "\n".join(parts)


def prepend_agent_instructions(system: str, agent_context: dict | None) -> str:
    """Prepend agent settings to a system prompt."""
    block = build_agent_instruction_block(agent_context)
    if not block:
        return system
    if system.strip():
        return f"{block}\n\n{system.strip()}"
    return block
