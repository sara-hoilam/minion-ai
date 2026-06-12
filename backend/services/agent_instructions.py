"""Agent settings block — always injected into LLM calls for task execution."""

from __future__ import annotations

from backend.services.thinking_principles import (
    data_freshness_instruction_block,
    first_principles_instruction_block,
    temporal_context_line,
)


def build_agent_instruction_block(agent_context: dict | None) -> str:
    """
    User-authored agent settings from AI agent configuration.
    Kept separate from auto-extracted conversation memory.
    """
    ctx = agent_context or {}
    parts: list[str] = [f"Temporal context: {temporal_context_line()}"]

    name = ctx.get("full_name") or "Agent"
    role_bits = [b for b in (ctx.get("current_job"), ctx.get("field"), ctx.get("industry")) if b]
    if role_bits:
        parts.append(f"Agent profile: {name} — {', '.join(role_bits)}.")
    else:
        parts.append(f"Agent profile: {name}.")

    if ctx.get("skillset"):
        parts.append(f"Core skillset: {ctx['skillset']}.")

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

    first_principles = first_principles_instruction_block(ctx)
    if first_principles:
        parts.append(f"Core reasoning approach (always follow):\n{first_principles}")

    data_freshness = data_freshness_instruction_block(ctx)
    if data_freshness:
        parts.append(f"Data currency (always follow):\n{data_freshness}")

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
