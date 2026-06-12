"""Skill-based framework construction."""

from pathlib import Path

from backend.services.skill_framework import (
    MANAGER_ID,
    MAX_AGENT_SKILLS,
    build_skill_framework,
    breakdown_from_user_skills,
    infer_skill_breakdown,
    normalize_skillset,
)


def test_normalize_skillset_caps_at_max():
    raw = ", ".join(f"Skill {i}" for i in range(12))
    normalized = normalize_skillset(raw)
    assert len(normalized.split(", ")) == MAX_AGENT_SKILLS


def test_infer_skills_from_jd_and_skillset():
    jd = {
        "title": "Analyst — Bot",
        "summary": "Data work.",
        "responsibilities": [
            "Write SQL queries for weekly KPI reporting",
            "Build executive slide decks for board meetings",
        ],
    }
    context = {"skillset": "SQL, Tableau", "full_name": "Bot", "field": "Data Analytics", "industry": "SaaS"}

    breakdown = infer_skill_breakdown(jd, context)
    skill_names = {b["skill"].lower() for b in breakdown}
    assert "sql" in " ".join(skill_names) or any("sql" in s.lower() for s in skill_names)
    assert len(breakdown) >= 2


def test_skill_framework_has_manager_and_interactions():
    jd = {
        "title": "Analyst — Data Bot",
        "summary": "AI analyst.",
        "responsibilities": [
            "Own weekly KPI reporting with SQL",
            "Present findings in executive slides",
        ],
    }
    context = {
        "full_name": "Data Bot",
        "field": "Data Analytics",
        "industry": "SaaS",
        "skillset": "SQL, Tableau, Business acumen",
    }

    result = build_skill_framework(jd, context)
    fw = result["framework"]

    assert fw["manager"]["id"] == MANAGER_ID
    agents = fw["agents"]
    assert any(a["id"] == MANAGER_ID for a in agents)
    skill_agents = [a for a in agents if a.get("type") == "skill"]
    assert len(skill_agents) >= 2
    assert all(a.get("skill_md") for a in agents)
    assert len(fw["interactions"]) >= len(skill_agents) * 2
    assert fw["skill_breakdown"]


def test_breakdown_from_user_skills_one_subagent_per_skill():
    jd = {
        "title": "Analyst — Finance",
        "summary": "Finance work.",
        "responsibilities": ["Manage P&L and cash flow reporting"],
    }
    breakdown = breakdown_from_user_skills(
        ["Cash flow", "P&L management", "Valuation"],
        jd,
    )
    skill_names = [b["skill"] for b in breakdown]
    assert skill_names == ["Cash flow", "P&L management", "Valuation"]
    assert all(len(b["member_skills"]) == 1 for b in breakdown)


def test_build_framework_from_user_skills_only():
    jd = {
        "title": "Analyst — Riley",
        "summary": "Finance agent.",
        "responsibilities": ["Build forecasts", "Report to board"],
    }
    context = {
        "full_name": "Riley",
        "field": "Finance",
        "industry": "SaaS",
        "skillset": "Cash flow, P&L management, Valuation",
    }
    fw = build_skill_framework(jd, context, from_user_skills_only=True)["framework"]
    skill_agents = [a for a in fw["agents"] if a.get("type") == "skill"]
    skill_names = [a["skill"] for a in skill_agents]
    assert skill_names == ["Cash flow", "P&L management", "Valuation"]


def test_skill_agents_not_one_per_responsibility():
    jd = {
        "title": "Role — Bot",
        "summary": "Many duties.",
        "responsibilities": ["Task A", "Task B", "Task C", "Task D"],
    }
    context = {"skillset": "SQL, Python", "full_name": "Bot", "field": "Ops", "industry": "SaaS"}

    fw = build_skill_framework(jd, context)["framework"]
    skill_agents = [a for a in fw["agents"] if a.get("type") == "skill"]
    assert len(skill_agents) < len(jd["responsibilities"])
