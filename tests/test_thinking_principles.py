"""First principles thinking defaults for all agents."""

from backend.app import create_app
from backend.services.agent_instructions import build_agent_instruction_block
from backend.services.thinking_principles import (
    CURRENT_DATA_SKILL,
    FIRST_PRINCIPLES_SKILL,
    enrich_agent_context,
    is_platform_skill,
    strip_platform_instruction_blocks,
    user_skillset,
    user_skills_list,
    today_label,
)


def test_user_skills_list_excludes_platform_skills():
    raw = f"{FIRST_PRINCIPLES_SKILL}, SQL, {CURRENT_DATA_SKILL}, Tableau"
    skills = user_skills_list(raw)
    assert skills == ["SQL", "Tableau"]
    assert not any(is_platform_skill(s) for s in skills)


def test_user_skillset_caps_at_eight():
    raw = ", ".join(f"Skill {i}" for i in range(12))
    assert len(user_skillset(raw).split(", ")) == 8


def test_enrich_agent_context_keeps_user_skills_only():
    ctx = enrich_agent_context({
        "full_name": "Aria",
        "skillset": f"{FIRST_PRINCIPLES_SKILL}, SQL, Tableau, {CURRENT_DATA_SKILL}",
        "working_instructions": "Be concise.",
    })
    assert FIRST_PRINCIPLES_SKILL not in ctx["skillset"]
    assert CURRENT_DATA_SKILL not in ctx["skillset"]
    assert ctx["skillset"] == "SQL, Tableau"
    assert ctx["working_instructions"] == "Be concise."


def test_instruction_block_includes_platform_defaults_in_prompt():
    block = build_agent_instruction_block({
        "full_name": "Sara",
        "current_job": "Analyst",
        "skillset": "SQL",
    })
    assert "first principles" in block.lower()
    assert "fundamental facts" in block.lower()
    assert "temporal context" in block.lower()
    assert today_label() in block
    assert "latest available data" in block.lower()
    assert "Core skillset: SQL." in block


def test_instruction_block_omits_platform_skills_from_skillset_line():
    block = build_agent_instruction_block({
        "full_name": "Sara",
        "skillset": f"{FIRST_PRINCIPLES_SKILL}, SQL",
    })
    assert FIRST_PRINCIPLES_SKILL not in block.split("Core skillset:")[1].split(".")[0]


def test_strip_platform_instruction_blocks():
    from backend.services.thinking_principles import (
        DATA_FRESHNESS_INSTRUCTIONS,
        FIRST_PRINCIPLES_INSTRUCTIONS,
    )

    merged = f"{FIRST_PRINCIPLES_INSTRUCTIONS}\n\n{DATA_FRESHNESS_INSTRUCTIONS}\n\nCustom note."
    assert strip_platform_instruction_blocks(merged) == "Custom note."


def test_create_agent_stores_user_skills_only():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={
        "email": "fp@test.com",
        "password": "securepass1",
        "first_name": "Test",
        "last_name": "User",
    })
    client.post("/api/profile/background", json={
        "full_name": "Owner",
        "field": "Finance",
        "skillset": "FP&A",
        "current_job": "Analyst",
        "industry": "SaaS",
    })
    fw = client.post("/api/agents/framework-preview", json={
        "full_name": "Nova",
        "field": "Finance",
        "skillset": "FP&A, SQL",
        "current_job": "Analyst",
        "industry": "SaaS",
        "job_description": {
            "title": "Analyst",
            "summary": "Finance agent.",
            "responsibilities": ["Build forecasts", "Analyze data"],
        },
    }).get_json()
    session_id = client.post("/api/agents/create", json={
        "full_name": "Nova",
        "field": "Finance",
        "skillset": "FP&A, SQL",
        "current_job": "Analyst",
        "industry": "SaaS",
        "job_description": {
            "title": "Analyst",
            "summary": "Finance agent.",
            "responsibilities": ["Build forecasts", "Analyze data"],
        },
        "framework_design": {
            "framework": fw["framework"],
            "construction_answers": {},
        },
    }).get_json()["session_id"]

    agent = client.get(f"/api/agents/{session_id}").get_json()
    assert FIRST_PRINCIPLES_SKILL not in agent["skillset"]
    assert CURRENT_DATA_SKILL not in agent["skillset"]
    assert "FP&A" in agent["skillset"]
    assert "first principles" not in (agent.get("working_instructions") or "").lower()
