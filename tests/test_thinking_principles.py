"""First principles thinking defaults for all agents."""

from backend.app import create_app
from backend.services.agent_instructions import build_agent_instruction_block
from backend.services.thinking_principles import (
    CURRENT_DATA_SKILL,
    FIRST_PRINCIPLES_SKILL,
    enrich_agent_context,
    ensure_first_principles_in_skillset,
    today_label,
)


def test_ensure_first_principles_in_skillset():
    assert FIRST_PRINCIPLES_SKILL in ensure_first_principles_in_skillset("SQL, Python")
    again = ensure_first_principles_in_skillset(
        ensure_first_principles_in_skillset("SQL, Python"),
    )
    assert again.count(FIRST_PRINCIPLES_SKILL) == 1


def test_enrich_agent_context_sets_skill_and_instructions():
    ctx = enrich_agent_context({
        "full_name": "Aria",
        "skillset": "SQL, Tableau",
    })
    assert FIRST_PRINCIPLES_SKILL in ctx["skillset"]
    assert CURRENT_DATA_SKILL in ctx["skillset"]
    assert "first principles" in ctx["working_instructions"].lower()
    assert "latest available data" in ctx["working_instructions"].lower()


def test_instruction_block_includes_first_principles_for_legacy_agents():
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


def test_instruction_block_skips_duplicate_first_principles():
    custom = "Always apply first principles thinking to forecasts."
    block = build_agent_instruction_block({
        "full_name": "Sara",
        "working_instructions": custom,
    })
    assert block.count("Core reasoning approach") == 0
    assert custom in block
    assert today_label() in block


def test_instruction_block_skips_duplicate_data_freshness():
    custom = "Use the latest available data for every benchmark."
    block = build_agent_instruction_block({
        "full_name": "Sara",
        "working_instructions": custom,
    })
    assert block.count("Data currency") == 0
    assert custom in block
    assert today_label() in block


def test_create_agent_includes_first_principles_skill():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": False,
    })
    client = app.test_client()
    client.post("/api/auth/register", json={"email": "fp@test.com", "password": "securepass1", "first_name": "Test", "last_name": "User"})
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
    assert FIRST_PRINCIPLES_SKILL in agent["skillset"]
    assert CURRENT_DATA_SKILL in agent["skillset"]
    assert "first principles" in (agent.get("working_instructions") or "").lower()
    assert "latest available data" in (agent.get("working_instructions") or "").lower()
