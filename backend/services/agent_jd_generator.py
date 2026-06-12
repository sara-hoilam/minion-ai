"""Generate editable job description draft from agent persona."""

import json
import re

from backend.services.cursor_llm import complete as cursor_complete
from backend.services.cursor_llm import is_configured as cursor_configured

JD_SYSTEM_PROMPT = """You draft a concise job description for an AI agent hire.
The user is the hiring manager and will edit this directly.

Output ONLY role and responsibilities — no schedule, no day-to-day timeline, no validation questions.

Rules:
- Ground responsibilities in the provided skills and industry.
- 4–6 specific, actionable responsibility bullets.
- Summary is 2–3 sentences max.
- Title format: "{job_title} — {agent_name}"

Respond with valid JSON only (no markdown fences):
{
  "job_description": {
    "title": "string",
    "summary": "string",
    "responsibilities": ["string", ...]
  }
}
"""

JD_USER_PROMPT = """Agent persona:
- Agent name: {agent_name}
- Field: {field}
- Job title: {job_title}
- Industry: {industry}
- Core skills: {skills}
"""


def _skills_list(skillset: str) -> list[str]:
    if not skillset:
        return []
    return [s.strip() for s in skillset.replace("\n", ",").split(",") if s.strip()]


def _rule_based_jd(context: dict) -> dict:
    name = context.get("full_name") or "Agent"
    field = context.get("field") or "Professional"
    job = context.get("current_job") or "Specialist"
    industry = context.get("industry") or "your organization"
    skills = _skills_list(context.get("skillset") or "")
    skill_text = ", ".join(skills[:6]) if skills else "core domain skills"

    return {
        "job_description": {
            "title": f"{job} — {name}",
            "summary": (
                f"{name} is an AI agent operating as a {job} in {field}, "
                f"serving {industry}. The role applies {skill_text} to deliver "
                f"analysis, recommendations, and stakeholder-ready outputs."
            ),
            "responsibilities": [
                f"Lead {field.lower()} workstreams using {skill_text}",
                "Translate ambiguous requests into scoped tasks with clear deliverables",
                f"Produce role-appropriate analysis and recommendations for {industry} context",
                "Communicate findings clearly to stakeholders and flag assumptions early",
                "Maintain consistent quality standards across recurring workflows",
            ],
        },
    }


def _parse_ai_json(text: str) -> dict | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def _ai_jd(context: dict) -> dict | None:
    if not cursor_configured():
        return None
    try:
        skills = ", ".join(_skills_list(context.get("skillset") or ""))
        user_prompt = JD_USER_PROMPT.format(
            agent_name=context.get("full_name") or "Agent",
            field=context.get("field") or "Professional",
            job_title=context.get("current_job") or "Specialist",
            industry=context.get("industry") or "General",
            skills=skills or "general professional skills",
        )
        raw = cursor_complete(JD_SYSTEM_PROMPT, user_prompt)
        return _parse_ai_json(raw) if raw else None
    except Exception:
        return None


def generate_jd_draft(context: dict) -> dict:
    result = _ai_jd(context)
    if result and result.get("job_description", {}).get("responsibilities"):
        result["source"] = "ai"
        return result

    result = _rule_based_jd(context)
    result["source"] = "template"
    return result
