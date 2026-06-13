"""Skill-based multi-agent framework: JD → skills → agents, manager, interactions."""

from __future__ import annotations

import re

from backend.services.thinking_principles import (
    DATA_FRESHNESS_INSTRUCTIONS,
    FIRST_PRINCIPLES_INSTRUCTIONS,
    user_skillset,
)

MANAGER_ID = "manager"
MAX_AGENT_SKILLS = 8

SKILL_INFERENCE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(sql|query|queries|database|warehouse|etl|dbt)\b", re.I), "SQL query"),
    (re.compile(r"\b(tableau|looker|dashboard|chart|visualiz|power\s*bi)\b", re.I), "Data visualization"),
    (re.compile(r"\b(forecast|model|regression|statistic|machine learning|predict)\b", re.I), "Statistical modeling"),
    (re.compile(r"\b(slide|deck|presentation|storytell|executive|board)\b", re.I), "Presentation & storytelling"),
    (re.compile(r"\b(stakeholder|business case|strategy|roi|revenue|acumen)\b", re.I), "Business acumen"),
    (re.compile(r"\b(python|script|automat|pipeline)\b", re.I), "Python automation"),
    (re.compile(r"\b(compliance|audit|governance|regulat)\b", re.I), "Compliance & governance"),
    (re.compile(r"\b(communicat|report|write|email|memo|brief)\b", re.I), "Written communication"),
    (re.compile(r"\b(variance|fp&a|budget|financial|forecast)\b", re.I), "Financial analysis"),
    (re.compile(r"\b(seo|marketing|campaign|growth)\b", re.I), "Growth marketing"),
    (re.compile(r"\b(process|kpi|operations|workflow)\b", re.I), "Process optimization"),
]

PIPELINE_ORDER: dict[str, int] = {
    "sql query": 10,
    "python automation": 20,
    "data & analytics": 25,
    "statistical modeling": 30,
    "statistical analysis": 32,
    "financial accounting": 34,
    "financial analysis": 35,
    "financial modeling & valuation": 36,
    "data visualization": 40,
    "process optimization": 45,
    "business acumen": 50,
    "growth marketing": 55,
    "compliance & governance": 58,
    "investor & board reporting": 59,
    "presentation & storytelling": 60,
    "written communication": 65,
    "domain expertise": 70,
}

def skills_list(skillset: str) -> list[str]:
    if not skillset:
        return []
    return [s.strip() for s in skillset.replace("\n", ",").split(",") if s.strip()]


def normalize_skillset(skillset: str | None, max_skills: int = MAX_AGENT_SKILLS) -> str:
    """Return user skillset capped at max_skills (platform skills excluded)."""
    return user_skillset(skillset, max_skills)


def skill_slug(skill: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", skill.lower()).strip("_")
    return slug[:40] or "skill"


def _canonical_skill(skill: str) -> str:
    aliases = {
        "sql": "SQL query",
        "tableau": "Data visualization",
        "looker": "Data visualization",
        "power bi": "Data visualization",
        "slides": "Presentation & storytelling",
        "storytelling": "Presentation & storytelling",
        "fp&a": "Financial analysis",
        "forecasting": "Statistical modeling",
        "python": "Python automation",
        "excel": "Financial analysis",
    }
    key = skill.strip().lower()
    return aliases.get(key, skill.strip())


def _skills_overlap(a: str, b: str) -> bool:
    a_l, b_l = a.lower(), b.lower()
    if a_l == b_l:
        return True
    return a_l in b_l or b_l in a_l


def _merge_unique_skills(candidates: list[str], max_skills: int) -> list[str]:
    merged: list[str] = []
    for raw in candidates:
        skill = _canonical_skill(raw)
        if not skill:
            continue
        if any(_skills_overlap(skill, existing) for existing in merged):
            continue
        merged.append(skill)
        if len(merged) >= max_skills:
            break
    return merged


def _infer_skills_from_text(text: str) -> set[str]:
    found: set[str] = set()
    for pattern, skill_name in SKILL_INFERENCE_PATTERNS:
        if pattern.search(text):
            found.add(skill_name)
    return found


def _jd_supports_for_skills(skills: list[str], jd: dict) -> list[str]:
    responsibilities = jd.get("responsibilities") or []
    if not responsibilities:
        label = skills[0] if skills else "assigned skills"
        return [f"Apply {label} expertise to user requests"]

    supports: list[str] = []
    for resp in responsibilities:
        resp_lower = resp.lower()
        for skill in skills:
            sl = skill.lower()
            if sl in resp_lower:
                supports.append(resp)
                break
            if any(w in resp_lower for w in sl.split() if len(w) > 3):
                supports.append(resp)
                break
            inferred = _infer_skills_from_text(resp)
            if any(_skills_overlap(skill, inf) for inf in inferred):
                supports.append(resp)
                break

    if not supports:
        supports = responsibilities[:2]
    return supports[:4]


def breakdown_from_user_skills(
    user_skills: list[str],
    jd: dict,
    max_subagents: int = MAX_AGENT_SKILLS,
) -> list[dict]:
    """Map each sidebar skill to its own subagent (authoritative, no grouping)."""
    breakdown: list[dict] = []
    for skill in user_skills:
        name = (skill or "").strip()
        if not name:
            continue
        breakdown.append({
            "skill": name,
            "member_skills": [name],
            "supports_responsibilities": _jd_supports_for_skills([name], jd),
            "rationale": f"Applies {name} to JD deliverables",
        })
        if len(breakdown) >= max_subagents:
            break
    return breakdown


def infer_skill_breakdown(jd: dict, context: dict, max_skills: int = 8) -> list[dict]:
    """Derive skills required to fulfill JD responsibilities."""
    user_skills = skills_list(context.get("skillset") or "")
    responsibilities = jd.get("responsibilities") or []
    resp_skill_map: dict[str, set[str]] = {}

    for resp in responsibilities:
        inferred = _infer_skills_from_text(resp)
        if not inferred:
            inferred = {"Business acumen"}
        resp_skill_map[resp] = inferred

    candidates: list[str] = list(user_skills)
    for resp_skills in resp_skill_map.values():
        candidates.extend(resp_skills)

    ordered_skills = _merge_unique_skills(candidates, max_skills)
    if not ordered_skills:
        ordered_skills = ["Domain expertise"]
    breakdown: list[dict] = []

    for skill in ordered_skills:
        supports: list[str] = []
        skill_lower = skill.lower()

        for resp, resp_skills in resp_skill_map.items():
            if skill_lower in resp.lower():
                supports.append(resp)
                continue
            if any(
                skill_lower in rs.lower() or rs.lower() in skill_lower
                for rs in resp_skills
            ):
                supports.append(resp)

        if not supports:
            for resp in responsibilities:
                if any(word in resp.lower() for word in skill_lower.split() if len(word) > 3):
                    supports.append(resp)

        if not supports and responsibilities:
            supports = [responsibilities[len(breakdown) % len(responsibilities)]]

        breakdown.append({
            "skill": skill,
            "supports_responsibilities": supports[:4],
            "rationale": (
                f"Required to deliver: {supports[0]}"
                if supports
                else "Core capability for this role"
            ),
        })

    return breakdown


_PLATFORM_STANDARDS_SECTION = f"""## Platform standards
{FIRST_PRINCIPLES_INSTRUCTIONS}

{DATA_FRESHNESS_INSTRUCTIONS}

Today's date is injected into every task at runtime.
"""


def build_skill_md(
    skill: str,
    agent_id: str,
    agent_name: str,
    field: str,
    industry: str,
    jd: dict,
    supports: list[str],
    peer_skills: list[str],
    agent_type: str = "skill",
    member_skills: list[str] | None = None,
) -> str:
    """Generate skill.md content for a sub-agent or the manager."""
    jd_title = jd.get("title") or f"{field} Agent"
    resp_lines = "\n".join(f"- {r}" for r in supports) if supports else "- All JD responsibilities"

    if agent_type == "manager":
        peer_lines = "\n".join(f"- **{s}** — delegate work and review outputs" for s in peer_skills)
        return f"""# Manager Agent

## Role
Orchestrates {agent_name}'s multi-agent team for **{jd_title}** ({field} · {industry}).

## Responsibilities
- Decompose incoming requests into skill-specific subtasks
- Assign work to the right skill agents
- Review sub-agent outputs for quality, completeness, and alignment with the JD
- Coordinate handoffs between specialists
- Approve or send back work for revision

## JD scope
{jd.get("summary", "")}

### Oversees delivery of
{resp_lines}

## Team
{peer_lines or "- Skill specialists (see framework interactions)"}

## Evaluation criteria
- Output matches the assigned JD responsibility
- Skill-appropriate methodology and artifacts
- Clear handoff context for downstream agents

{_PLATFORM_STANDARDS_SECTION}"""

    peer_lines = "\n".join(f"- {s}" for s in peer_skills if s.lower() != skill.lower())
    members = member_skills or [skill]
    if len(members) > 1:
        capability_body = (
            f"Covers these related capabilities under **{skill}**:\n"
            + "\n".join(f"- {m}" for m in members)
        )
    else:
        capability_body = f"- Execute tasks that require {skill.lower()}"
    return f"""# {skill}

## Agent
`{agent_id}` — skill specialist for **{agent_name}** ({field} · {industry})

## Purpose
Apply **{skill}** to fulfill parts of the confirmed job description.

## Supports JD responsibilities
{resp_lines}

## Capabilities
{capability_body}
- Produce deliverables ready for manager review or peer handoff
- Flag blockers and request clarification from the Manager Agent

## Inputs
- Task brief from Manager Agent (objective, constraints, deadline)
- Context from upstream skill agents when applicable

## Outputs
- Skill-specific artifacts (queries, analyses, slides, reports, etc.)
- Status summary for manager evaluation

## Collaborates with
- **Manager Agent** — receives tasks, submits outputs for evaluation
{("- Peers: " + ", ".join(peer_skills[:5])) if peer_lines else ""}

## Triggers
Work involving {skill.lower()} on: {supports[0][:80] if supports else jd_title}

{_PLATFORM_STANDARDS_SECTION}"""


def build_manager_agent(
    agent_name: str,
    field: str,
    industry: str,
    jd: dict,
    skill_names: list[str],
) -> dict:
    jd_title = jd.get("title") or f"{field} Agent"
    jd_summary = jd.get("summary") or ""
    peer_skills = skill_names

    skill_md = build_skill_md(
        skill="Management & orchestration",
        agent_id=MANAGER_ID,
        agent_name=agent_name,
        field=field,
        industry=industry,
        jd=jd,
        supports=jd.get("responsibilities") or [],
        peer_skills=peer_skills,
        agent_type="manager",
    )

    return {
        "id": MANAGER_ID,
        "role": "Manager Agent",
        "type": "manager",
        "skill": "Management & orchestration",
        "focus": (
            f"Distribute tasks across skill agents and evaluate outputs for {jd_title}"
        ),
        "skill_md": skill_md,
        "triggers": ["assign", "review", "coordinate", "evaluate", "delegate"],
    }


def build_skill_agent(
    entry: dict,
    agent_name: str,
    field: str,
    industry: str,
    jd: dict,
    all_skill_names: list[str],
) -> dict:
    skill = entry["skill"]
    member_skills = entry.get("member_skills") or [skill]
    agent_id = f"skill_{skill_slug(skill)}"
    supports = entry.get("supports_responsibilities") or []
    peers = [s for s in all_skill_names if s != skill]

    skill_md = build_skill_md(
        skill=skill,
        agent_id=agent_id,
        agent_name=agent_name,
        field=field,
        industry=industry,
        jd=jd,
        supports=supports,
        peer_skills=peers,
        member_skills=member_skills,
    )

    return {
        "id": agent_id,
        "role": f"{skill} Specialist",
        "type": "skill",
        "skill": skill,
        "member_skills": member_skills,
        "focus": entry.get("rationale") or f"Applies {skill} to JD deliverables",
        "supports_responsibilities": supports,
        "skill_md": skill_md,
        "triggers": _skill_triggers(skill, supports),
    }


def _skill_triggers(skill: str, supports: list[str]) -> list[str]:
    triggers = [w for w in skill.lower().split() if len(w) > 3]
    for resp in supports[:2]:
        triggers.extend(w for w in resp.lower().split()[:4] if len(w) > 3)
    seen: set[str] = set()
    unique: list[str] = []
    for t in triggers:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique[:6]


def _pipeline_rank(skill: str) -> int:
    return PIPELINE_ORDER.get(skill.lower(), 50)


def build_interactions(skill_agents: list[dict], manager_id: str = MANAGER_ID) -> list[dict]:
    """Define how manager and skill agents interact."""
    interactions: list[dict] = []

    for agent in skill_agents:
        sid = agent["id"]
        skill = agent.get("skill", agent.get("role", sid))
        interactions.append({
            "from": manager_id,
            "to": sid,
            "type": "delegation",
            "description": f"Manager assigns {skill.lower()} tasks with success criteria",
        })
        interactions.append({
            "from": sid,
            "to": manager_id,
            "type": "review",
            "description": f"{skill} specialist submits output for manager evaluation",
        })

    ordered = sorted(skill_agents, key=lambda a: _pipeline_rank(a.get("skill", "")))
    for i in range(len(ordered) - 1):
        src = ordered[i]
        dst = ordered[i + 1]
        interactions.append({
            "from": src["id"],
            "to": dst["id"],
            "type": "handoff",
            "description": (
                f"Pass {src.get('skill', 'work')} output to "
                f"{dst.get('skill', 'next specialist')} when downstream work is needed"
            ),
        })

    return interactions


def build_skill_framework(
    jd: dict,
    context: dict,
    *,
    from_user_skills_only: bool = False,
) -> dict:
    """Build complete skill-based framework preview payload."""
    agent_name = context.get("full_name") or "Agent"
    field = context.get("field") or "Professional"
    industry = context.get("industry") or "General"
    jd_title = jd.get("title") or f"{field} Agent"
    jd_summary = jd.get("summary") or ""

    if from_user_skills_only:
        user_skills = skills_list(context.get("skillset") or "")
        breakdown = breakdown_from_user_skills(user_skills, jd)
    else:
        breakdown = infer_skill_breakdown(jd, context)
    skill_names = [b["skill"] for b in breakdown]

    skill_agents = [
        build_skill_agent(entry, agent_name, field, industry, jd, skill_names)
        for entry in breakdown
    ]
    manager = build_manager_agent(agent_name, field, industry, jd, skill_names)
    interactions = build_interactions(skill_agents)

    all_agents = [manager, *skill_agents]
    summary_snippet = jd_summary[:160] + ("…" if len(jd_summary) > 160 else "")

    framework = {
        "manager": {
            "id": MANAGER_ID,
            "role": manager["role"],
            "description": (
                f"Manager Agent for {agent_name}: decomposes work, delegates to "
                f"{len(skill_agents)} skill specialists, and evaluates deliverables "
                f"against «{jd_title}»."
            ),
            "responsibilities": [
                "Decompose incoming requests into skill-specific subtasks",
                "Delegate to the appropriate skill agent",
                "Evaluate output quality and JD alignment",
                "Coordinate cross-skill handoffs",
            ],
        },
        "skill_breakdown": breakdown,
        "agents": all_agents,
        "interactions": interactions,
        "orchestrator": {
            "role": "manager_orchestrator",
            "description": (
                f"Manager-led skill framework for {agent_name} per JD «{jd_title}». "
                f"{summary_snippet}"
            ).strip(),
            "routing_rules": [
                {"intent": f"needs {a['skill'].lower()}", "agent": a["id"]}
                for a in skill_agents[:6]
            ],
        },
    }

    return {"framework": framework}


def dedupe_skill_agents(agents: list[dict], max_skills: int = 8) -> list[dict]:
    """Collapse overlapping skill agents; keep a single manager."""
    managers = [
        a for a in agents
        if a.get("id") == MANAGER_ID or a.get("type") == "manager"
    ]
    skill_agents = [
        a for a in agents
        if a.get("id") != MANAGER_ID and a.get("type") != "manager"
    ]
    deduped: list[dict] = []
    for agent in skill_agents:
        skill = _canonical_skill(agent.get("skill") or agent.get("role") or "")
        if not skill:
            continue
        if any(_skills_overlap(skill, existing.get("skill", "")) for existing in deduped):
            continue
        agent["skill"] = skill
        if not agent.get("role"):
            agent["role"] = f"{skill} Specialist"
        if not agent.get("id") or agent["id"] == "agent":
            agent["id"] = f"skill_{skill_slug(skill)}"
        deduped.append(agent)
        if len(deduped) >= max_skills:
            break
    return (managers[:1] if managers else []) + deduped


def enrich_framework_agents(framework: dict, jd: dict, context: dict) -> dict:
    """Ensure every agent has skill_md and manager is present."""
    agent_name = context.get("full_name") or "Agent"
    field = context.get("field") or "Professional"
    industry = context.get("industry") or "General"

    agents = dedupe_skill_agents(framework.get("agents") or [])
    skill_agents = [a for a in agents if a.get("type") == "skill" or a.get("skill")]
    if not any(a.get("id") == MANAGER_ID or a.get("type") == "manager" for a in agents):
        breakdown = framework.get("skill_breakdown") or infer_skill_breakdown(jd, context)
        skill_names = [b["skill"] for b in breakdown]
        manager = build_manager_agent(agent_name, field, industry, jd, skill_names)
        agents = [manager] + [a for a in agents if a.get("id") != MANAGER_ID]

    skill_names = [
        a.get("skill") for a in agents
        if a.get("type") == "skill" or (a.get("skill") and a.get("id") != MANAGER_ID)
    ]

    for agent in agents:
        if not agent.get("skill_md"):
            supports = agent.get("supports_responsibilities") or jd.get("responsibilities") or []
            is_manager = agent.get("type") == "manager" or agent.get("id") == MANAGER_ID
            skill = agent.get("skill") or ("Management & orchestration" if is_manager else agent.get("role", "Skill"))
            peers = [s for s in skill_names if s != skill]
            agent["skill_md"] = build_skill_md(
                skill=skill,
                agent_id=agent.get("id", "agent"),
                agent_name=agent_name,
                field=field,
                industry=industry,
                jd=jd,
                supports=supports if not is_manager else jd.get("responsibilities") or [],
                peer_skills=peers if not is_manager else skill_names,
                agent_type="manager" if is_manager else "skill",
                member_skills=agent.get("member_skills") if not is_manager else None,
            )
        if agent.get("id") != MANAGER_ID and not agent.get("type"):
            agent["type"] = "skill"

    framework["agents"] = agents
    if not framework.get("interactions"):
        skill_only = [a for a in agents if a.get("type") == "skill" or a.get("id", "").startswith("skill_")]
        framework["interactions"] = build_interactions(skill_only)
    if not framework.get("manager"):
        mgr = next((a for a in agents if a.get("id") == MANAGER_ID), None)
        if mgr:
            framework["manager"] = {
                "id": MANAGER_ID,
                "role": mgr.get("role", "Manager Agent"),
                "description": mgr.get("focus", "Distributes and evaluates work"),
                "responsibilities": [
                    "Decompose incoming requests into skill-specific subtasks",
                    "Delegate to the appropriate skill agent",
                    "Evaluate output quality and JD alignment",
                    "Coordinate cross-skill handoffs",
                ],
            }
    if not framework.get("skill_breakdown"):
        framework["skill_breakdown"] = infer_skill_breakdown(jd, context)

    return framework
