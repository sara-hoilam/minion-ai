"""Build agent profile and framework from personalization context (no Studio assessment)."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from backend.services.skill_framework import MANAGER_ID
from backend.services.thinking_principles import CURRENT_DATA_SKILL, FIRST_PRINCIPLES_SKILL


def agent_file_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "agent").lower()).strip("_")
    return slug[:60] or "agent"


def artifact_download_filename(artifact_type: str, agent_name: str) -> str | None:
    slug = agent_file_slug(agent_name)
    if artifact_type == "agent_framework_json":
        return f"{slug}_agent_framework.json"
    if artifact_type == "agent_skill_md":
        return f"{slug}_skill.md"
    return None


def _skills_list(skillset: str) -> list[str]:
    if not skillset:
        return []
    return [s.strip() for s in skillset.replace("\n", ",").split(",") if s.strip()]


def _agent_system_prompt(name: str, agent: dict, field: str, industry: str) -> str:
    skill = agent.get("skill") or agent.get("role", "")
    focus = agent.get("focus", "")
    agent_type = agent.get("type", "skill")

    reasoning = (
        f"Apply {FIRST_PRINCIPLES_SKILL.lower()} on every task. "
        f"Use the latest available data when possible ({CURRENT_DATA_SKILL.lower()}); "
        f"today's date is provided in task context."
    )

    if agent_type == "manager" or agent.get("id") == MANAGER_ID:
        return (
            f"You are the Manager Agent for {name}.\n"
            f"Role: decompose work, delegate to skill specialists, evaluate outputs, "
            f"and coordinate handoffs.\n"
            f"Field: {field} | Industry: {industry}\n"
            f"Scope: {focus}\n"
            f"{reasoning}"
        )

    supports = agent.get("supports_responsibilities") or []
    support_line = f"\nJD responsibilities: {'; '.join(supports[:3])}" if supports else ""
    return (
        f"You are {name}'s {skill} specialist.\n"
        f"Focus: {focus}{support_line}\n"
        f"Field: {field} | Industry: {industry}\n"
        f"Follow your skill.md spec. Submit outputs to the Manager Agent for review.\n"
        f"{reasoning}"
    )


def build_agent_profile(context: dict) -> str:
    name = context.get("full_name") or "My Agent"
    field = context.get("field") or "Professional"
    job = context.get("current_job") or "Specialist"
    industry = context.get("industry") or "—"
    skills = context.get("skillset") or "—"
    jd = context.get("job_description") or {}
    construction = context.get("framework_design", {}).get("construction_answers") or {}
    framework = context.get("framework_design", {}).get("framework") or {}

    jd_section = ""
    if jd:
        responsibilities = "\n".join(f"- {r}" for r in jd.get("responsibilities", []))
        jd_section = f"""
## Job description

**{jd.get("title", job)}**

{jd.get("summary", "")}

### Responsibilities
{responsibilities}
"""

    skill_section = ""
    breakdown = framework.get("skill_breakdown") or []
    if breakdown:
        skill_lines = "\n".join(
            f"- **{b['skill']}** — {b.get('rationale', '')}" for b in breakdown
        )
        skill_section = f"""
## Skill breakdown

{skill_lines}
"""

    interaction_section = ""
    interactions = framework.get("interactions") or []
    if interactions:
        interaction_lines = "\n".join(
            f"- {i.get('from')} → {i.get('to')} ({i.get('type')}): {i.get('description', '')}"
            for i in interactions[:12]
        )
        interaction_section = f"""
## Agent interactions

{interaction_lines}
"""

    clarifications = ""
    if construction:
        clarifications = "\n### Framework design clarifications\n"
        for qid, answer in construction.items():
            if answer and str(answer).strip():
                clarifications += f"- {answer.strip()}\n"

    return f"""# Agent Profile: {name}

> Created by Minion AI on {datetime.now(timezone.utc).strftime("%Y-%m-%d")}
> Domain: {field} · {industry}

## Identity

| Attribute | Value |
|-----------|-------|
| Agent name | {name} |
| Field | {field} |
| Role | {job} |
| Industry | {industry} |
| Core skills | {skills} |
{jd_section}{skill_section}{interaction_section}{clarifications}
## Framework

Skill-based multi-agent framework with a Manager Agent that delegates to skill specialists.
Each skill agent has a `skill.md` specification in the artifacts folder.
"""


def build_agent_framework(context: dict) -> dict:
    name = context.get("full_name") or "My Agent"
    field = context.get("field") or "Professional"
    job = context.get("current_job") or "Specialist"
    industry = context.get("industry") or ""
    skills = _skills_list(context.get("skillset") or "")

    design = context.get("framework_design") or {}
    designed = design.get("framework")

    if designed:
        agents = []
        for a in designed.get("agents", []):
            agents.append({
                "id": a.get("id"),
                "role": a.get("role"),
                "type": a.get("type", "skill"),
                "skill": a.get("skill"),
                "system_prompt": _agent_system_prompt(name, a, field, industry),
                "skill_md": a.get("skill_md", ""),
                "supports_responsibilities": a.get("supports_responsibilities", []),
                "triggers": a.get("triggers", []),
            })

        skill_count = sum(1 for a in agents if a.get("type") == "skill" or a.get("id", "").startswith("skill_"))

        return {
            "version": "1.1",
            "profile_name": name,
            "field": field,
            "industry": industry,
            "job_title": job,
            "job_description": context.get("job_description"),
            "manager": designed.get("manager"),
            "skill_breakdown": designed.get("skill_breakdown", []),
            "interactions": designed.get("interactions", []),
            "training_progress": {
                "tasks_assessed": 0,
                "agents_active": len(agents),
                "skill_agents": skill_count,
                "source": "jd_skill_framework",
            },
            "orchestrator": designed.get("orchestrator", {}),
            "agents": agents,
            "style_profile": {
                "field": field,
                "industry": industry,
                "skills": skills,
            },
        }

    return {
        "version": "1.1",
        "profile_name": name,
        "field": field,
        "industry": industry,
        "job_title": job,
        "training_progress": {"tasks_assessed": 0, "agents_active": 1, "source": "personalization"},
        "orchestrator": {
            "description": f"Routes work for {name} ({job}, {field}).",
            "routing_rules": [
                {"intent": "domain_question", "agent": "domain_expert"},
            ],
        },
        "agents": [
            {
                "id": "domain_expert",
                "role": f"{field} Expert",
                "type": "skill",
                "system_prompt": f"You are {name}, a {job} in {field}.",
                "triggers": [field.lower()],
            },
        ],
        "style_profile": {"field": field, "industry": industry, "skills": skills},
    }


def write_skill_md_file(user_dir: Path, context: dict) -> tuple[Path, str] | None:
    """Write combined skill spec as {agent_name}_skill.md."""
    name = context.get("full_name") or "agent"
    filename = artifact_download_filename("agent_skill_md", name)
    if not filename:
        return None

    framework = build_agent_framework(context)
    sections = [
        a.get("skill_md", "").strip()
        for a in framework.get("agents", [])
        if a.get("skill_md")
    ]
    if not sections:
        return None

    combined = f"# Skill specifications: {name}\n\n" + "\n\n---\n\n".join(sections)
    path = user_dir / filename
    path.write_text(combined, encoding="utf-8")
    return path, combined[:500]


def framework_to_json(framework: dict) -> str:
    return json.dumps(framework, indent=2)
