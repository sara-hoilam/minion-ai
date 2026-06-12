"""Design skill-based multi-agent framework from confirmed JD."""

import json
import re

from backend.services.cursor_llm import complete as cursor_complete
from backend.services.cursor_llm import is_configured as cursor_configured
from backend.services.skill_framework import (
    MANAGER_ID,
    breakdown_from_user_skills,
    build_skill_framework,
    enrich_framework_agents,
    infer_skill_breakdown,
    skills_list,
)

FRAMEWORK_SYSTEM_PROMPT = """You design a skill-based multi-agent framework for an AI agent hire.

The hiring manager confirmed the job description. Your job:
1. Break down the SKILLS required to complete the JD responsibilities (e.g. SQL query, business acumen, slide making) — do NOT map one agent per JD bullet.
2. Create one skill specialist agent per skill, each with a skill_md field (markdown spec for that skill agent).
3. ALWAYS include a Manager Agent (id: "manager") that distributes tasks to skill agents and evaluates their outputs.
4. Define interactions: manager→skill delegations, skill→manager reviews, and skill→skill handoffs when work flows between specialists.

Only include construction_questions when a real ambiguity would change skill assignment or interaction design.
If the JD is clear, return an empty construction_questions array.

Each construction question must provide exactly four multiple-choice options A–D and allow_manual: true.

Respond with valid JSON only:
{
  "framework": {
    "manager": {
      "id": "manager",
      "role": "Manager Agent",
      "description": "string",
      "responsibilities": ["Decompose tasks", "Delegate to skills", "Evaluate outputs", "Coordinate handoffs"]
    },
    "skill_breakdown": [
      {
        "skill": "SQL query",
        "supports_responsibilities": ["JD bullet this skill helps deliver"],
        "rationale": "Why this skill is needed"
      }
    ],
    "agents": [
      {
        "id": "manager",
        "role": "Manager Agent",
        "type": "manager",
        "skill": "Management & orchestration",
        "focus": "string",
        "skill_md": "# Manager Agent\\n...",
        "triggers": ["assign", "review"]
      },
      {
        "id": "skill_sql_query",
        "role": "SQL Query Specialist",
        "type": "skill",
        "skill": "SQL query",
        "focus": "string",
        "supports_responsibilities": ["..."],
        "skill_md": "# SQL query\\n...",
        "triggers": ["sql", "query"]
      }
    ],
    "interactions": [
      {
        "from": "manager",
        "to": "skill_sql_query",
        "type": "delegation",
        "description": "Manager assigns SQL work"
      },
      {
        "from": "skill_sql_query",
        "to": "manager",
        "type": "review",
        "description": "Submit query results for evaluation"
      },
      {
        "from": "skill_sql_query",
        "to": "skill_data_visualization",
        "type": "handoff",
        "description": "Pass results for charting"
      }
    ],
    "orchestrator": {
      "role": "manager_orchestrator",
      "description": "string — reference JD title",
      "routing_rules": [{"intent": "needs sql", "agent": "skill_sql_query"}]
    }
  },
  "construction_questions": []
}
"""

FRAMEWORK_USER_PROMPT = """Confirmed job description:

Title: {title}
Summary: {summary}

Responsibilities:
{responsibilities}

Agent: {agent_name} | Field: {field} | Industry: {industry}
User-listed skills (use as starting skill breakdown): {skills}

Infer additional skills from responsibilities if needed. Manager agent is mandatory.
"""


def _generic_responsibility(text: str) -> bool:
    generic = ("maintain", "support", "assist", "help", "various", "general")
    lower = text.lower()
    return len(text) < 40 or any(g in lower for g in generic)


def _mc_question(
    qid: str,
    context: str,
    question: str,
    option_labels: list[str],
    manual_placeholder: str = "Or type your own answer...",
) -> dict:
    letters = ["A", "B", "C", "D"]
    labels = (option_labels + [""] * 4)[:4]
    return {
        "id": qid,
        "context": context,
        "question": question,
        "options": [{"id": letters[i], "label": labels[i]} for i in range(4) if labels[i]],
        "allow_manual": True,
        "manual_placeholder": manual_placeholder,
    }


def _normalize_construction_questions(questions: list) -> list[dict]:
    normalized = []
    for q in questions or []:
        if not isinstance(q, dict) or not q.get("question"):
            continue
        options = q.get("options") or []
        if len(options) < 4:
            letters = ["A", "B", "C", "D"]
            rebuilt = []
            for i, letter in enumerate(letters):
                existing = next((o for o in options if o.get("id") == letter), None)
                label = (existing or {}).get("label") or f"Option {letter}"
                rebuilt.append({"id": letter, "label": label})
            options = rebuilt
        q = {**q, "options": options[:4], "allow_manual": q.get("allow_manual", True)}
        if "manual_placeholder" not in q:
            q["manual_placeholder"] = "Or type your own answer..."
        normalized.append(q)
    return normalized


def _resolve_breakdown(jd: dict, context: dict) -> list[dict]:
    """Single skill breakdown for preview — user skills are authoritative when present."""
    user_skills = skills_list(context.get("skillset") or "")
    if user_skills:
        return breakdown_from_user_skills(user_skills, jd)
    return infer_skill_breakdown(jd, context)


def _detect_ambiguities(
    jd: dict,
    context: dict,
    *,
    breakdown: list[dict] | None = None,
) -> list[dict]:
    """Return construction questions when skill assignment or interactions are unclear."""
    responsibilities = jd.get("responsibilities") or []
    if breakdown is None:
        breakdown = _resolve_breakdown(jd, context)
    questions = []

    if len(breakdown) >= 6:
        top = breakdown[:4]
        questions.append(_mc_question(
            "c_skill_priority",
            (
                f"The framework identified {len(breakdown)} skill agents. "
                "The Manager Agent needs a default skill lane when tasks are ambiguous."
            ),
            "Which skill should the Manager Agent prioritize for ambiguous incoming work?",
            [f"Prioritize {b['skill']}" for b in top],
            "Describe how the manager should triage ambiguous work...",
        ))

    generic = [r for r in responsibilities if _generic_responsibility(r)]
    if len(generic) >= 2:
        g0, g1 = generic[0], generic[1]
        questions.append(_mc_question(
            "c_scope",
            (
                "Some responsibilities are broad (e.g. "
                + g0[:60]
                + "). Skill agents need sharper deliverables."
            ),
            "How should skill agents narrow the most vague responsibilities?",
            [
                f"Map skills to deliverables for: {g0[:70]}",
                f"Map skills to deliverables for: {g1[:70]}",
                "Manager decomposes vague items per request",
                "Keep broad — manager routes dynamically",
            ],
            "Describe expected deliverables per skill...",
        ))

    skills = skills_list(context.get("skillset") or "")
    if len(skills) >= 6 and len(breakdown) >= 4:
        lead = breakdown[:4]
        questions.append(_mc_question(
            "c_handoff",
            (
                f"{len(skills)} skills were listed. "
                "Cross-skill handoffs affect how specialists pass work along."
            ),
            "Which skill-to-skill handoff is most critical in daily work?",
            [
                f"{lead[0]['skill']} → {lead[1]['skill']}" if len(lead) > 1 else f"Manager → {lead[0]['skill']}",
                f"{lead[1]['skill']} → {lead[2]['skill']}" if len(lead) > 2 else f"Manager → {lead[1]['skill']}",
                "All skills report to manager only — no peer handoffs",
                "Manager coordinates all handoffs case-by-case",
            ],
            "Describe the typical workflow order across skills...",
        ))

    return questions[:2]


def _parse_ai_json(text: str) -> dict | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def _ai_framework(jd: dict, context: dict, reporter=None) -> dict | None:
    if not cursor_configured():
        return None
    try:
        responsibilities = "\n".join(f"- {r}" for r in jd.get("responsibilities", []))
        skills = ", ".join(skills_list(context.get("skillset") or ""))
        user_prompt = FRAMEWORK_USER_PROMPT.format(
            title=jd.get("title", ""),
            summary=jd.get("summary", ""),
            responsibilities=responsibilities,
            agent_name=context.get("full_name") or "Agent",
            field=context.get("field") or "Professional",
            industry=context.get("industry") or "General",
            skills=skills,
        )

        def on_tick(status: str, elapsed: float) -> None:
            if not reporter:
                return
            pct = min(58, 32 + int(elapsed / 3))
            reporter.set_percent(pct, "Designing multi-agent framework")
            label = (status or "RUNNING").replace("_", " ").lower()
            reporter.log(
                f"AI designer running ({label}, {int(elapsed)}s)…",
                status="active",
                key="ai_design",
            )

        if reporter:
            reporter.log(
                "Sending framework design request to AI…",
                status="active",
                key="ai_design",
            )
        raw = cursor_complete(
            FRAMEWORK_SYSTEM_PROMPT,
            user_prompt,
            max_wait_s=240,
            on_tick=on_tick,
        )
        if reporter:
            reporter.complete_log("ai_design")
        return _parse_ai_json(raw) if raw else None
    except Exception:
        if reporter:
            reporter.complete_log("ai_design")
        return None


def _is_skill_framework(framework: dict) -> bool:
    if not framework:
        return False
    agents = framework.get("agents") or []
    has_manager = any(
        a.get("id") == MANAGER_ID or a.get("type") == "manager"
        for a in agents
    )
    has_skills = any(a.get("type") == "skill" or str(a.get("id", "")).startswith("skill_") for a in agents)
    return has_manager and has_skills and bool(framework.get("interactions"))


def _finalize_preview(
    result: dict,
    jd: dict,
    context: dict,
    source: str,
    reporter=None,
    *,
    breakdown: list[dict] | None = None,
) -> dict:
    framework = result.get("framework") or {}
    if breakdown and not framework.get("skill_breakdown"):
        framework["skill_breakdown"] = breakdown

    if not _is_skill_framework(framework):
        if reporter:
            reporter.set_percent(55, "Building from skill templates")
            reporter.log("AI output invalid — using skill template builder", status="done")
        user_skills = skills_list(context.get("skillset") or "")
        built = build_skill_framework(
            jd,
            context,
            from_user_skills_only=bool(user_skills),
        )
        framework = built["framework"]
    else:
        if reporter:
            reporter.set_percent(62, "Enriching agent specifications")
            reporter.log("Validating AI framework structure", status="done")
        if breakdown and not framework.get("skill_breakdown"):
            framework["skill_breakdown"] = breakdown
        if source != "template" or not all(a.get("skill_md") for a in framework.get("agents") or []):
            framework = enrich_framework_agents(framework, jd, context)
        if reporter:
            reporter.log("Enriched specialist prompts and skill specs", status="done")

    result["framework"] = framework
    if "construction_questions" not in result:
        if reporter:
            reporter.set_percent(78, "Checking for clarifications")
            reporter.log("Scanning for ambiguities that need your input", status="active", key="clarify")
        result["construction_questions"] = _detect_ambiguities(jd, context, breakdown=breakdown)
        if reporter:
            reporter.complete_log("clarify")
    result["construction_questions"] = _normalize_construction_questions(
        result["construction_questions"]
    )
    result["job_description_used"] = {
        "title": jd.get("title", ""),
        "summary": jd.get("summary", ""),
        "responsibilities": jd.get("responsibilities") or [],
    }
    result["source"] = source
    return result


def _log_template_scaffold(framework: dict, agent_name: str, reporter) -> None:
    agents = framework.get("agents") or []
    for agent in agents:
        if agent.get("type") == "manager" or agent.get("id") == MANAGER_ID:
            reporter.log(
                f"Manager agent — orchestrates {agent_name}'s team",
                status="done",
            )
        elif agent.get("type") == "skill":
            reporter.log(
                f"Specialist: {agent.get('skill') or agent.get('role')}",
                status="done",
            )
    interactions = framework.get("interactions") or []
    reporter.log(f"Wired {len(interactions)} delegation and handoff routes", status="done")


def _build_template_preview(
    jd: dict,
    context: dict,
    breakdown: list[dict],
    reporter=None,
) -> dict:
    """Rule-based framework — fast path when user skills are known."""
    user_skills = skills_list(context.get("skillset") or "")
    if reporter:
        reporter.set_percent(36, "Scaffolding manager and specialists")
    rule_result = build_skill_framework(
        jd,
        context,
        from_user_skills_only=bool(user_skills),
    )
    rule_result["construction_questions"] = _detect_ambiguities(
        jd, context, breakdown=breakdown,
    )
    if reporter:
        _log_template_scaffold(rule_result.get("framework") or {}, context.get("full_name") or "Agent", reporter)
    return _finalize_preview(
        rule_result, jd, context, "template", reporter=reporter, breakdown=breakdown,
    )


def generate_framework_preview(jd: dict, context: dict, reporter=None) -> dict:
    agent_name = context.get("full_name") or "Agent"
    title = jd.get("title") or "Role"
    user_skills = skills_list(context.get("skillset") or "")

    if reporter:
        reporter.set_percent(6, "Analyzing job description")
        reporter.log(f"Confirmed role: «{title}»", status="done")
        responsibilities = jd.get("responsibilities") or []
        reporter.log(
            f"Mapping {len(responsibilities)} responsibilities to specialist skills",
            status="done",
        )

    breakdown = _resolve_breakdown(jd, context)
    if reporter:
        reporter.set_percent(14, "Inferring skill breakdown")
        reporter.log(f"Identified {len(breakdown)} specialist skills", status="done")
        for i, entry in enumerate(breakdown[:8]):
            skill = entry.get("skill") or "Skill"
            rationale = (entry.get("rationale") or "Supports JD deliverables")[:90]
            reporter.log(f"{skill} — {rationale}", status="done")
            reporter.set_percent(14 + int((i + 1) / max(len(breakdown), 1) * 12), "Mapping specialist skills")

    use_template = bool(user_skills)
    if use_template:
        if reporter:
            reporter.set_percent(28, "Building framework from selected skills")
            reporter.log("Using your selected skills for specialist agents", status="done")
        result = _build_template_preview(jd, context, breakdown, reporter=reporter)
    else:
        if reporter:
            reporter.set_percent(28, "Designing multi-agent framework")
        ai_result = _ai_framework(jd, context, reporter=reporter)
        if ai_result and ai_result.get("framework"):
            if reporter:
                reporter.log("AI framework design received", status="done")
            result = _finalize_preview(
                ai_result, jd, context, "ai", reporter=reporter, breakdown=breakdown,
            )
        else:
            if reporter:
                if cursor_configured():
                    reporter.log("AI design unavailable — using skill templates", status="done")
                else:
                    reporter.log("Building framework from skill templates", status="done")
            result = _build_template_preview(jd, context, breakdown, reporter=reporter)

    if reporter:
        framework = result.get("framework") or {}
        agents = framework.get("agents") or []
        skill_count = len([a for a in agents if a.get("type") == "skill"])
        interaction_count = len(framework.get("interactions") or [])
        question_count = len(result.get("construction_questions") or [])
        reporter.set_percent(90, "Finalizing framework")
        reporter.log(
            f"Framework complete — manager + {skill_count} specialists, "
            f"{interaction_count} routes",
            status="done",
        )
        if question_count:
            reporter.log(
                f"{question_count} clarification question(s) for you to answer",
                status="done",
            )
        else:
            reporter.log("No clarification questions needed", status="done")

    return result
