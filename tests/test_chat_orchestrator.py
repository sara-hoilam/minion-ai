"""Chat orchestrator — manager decomposition and distinct subtask assignments."""

from backend.services.chat_orchestrator import (
    CONFIRMED_MAX_SUBTASKS_CEILING,
    DEFAULT_MAX_SUBTASKS,
    _is_direct_answer,
    _is_modeling_skill,
    _manager_decompose_rule,
    _match_skills_for_request,
    _max_subtasks,
    _rank_relevant_agents,
    _run_subtask,
    _should_use_team_mode,
    _use_expanded_planning_cap,
    run_agent_turn,
)
from backend.services.skill_framework import build_skill_framework


def _sample_framework():
    jd = {
        "title": "Analyst — Test",
        "summary": "Finance analyst agent.",
        "responsibilities": [
            "Build forecasts and variance analysis",
            "Query data warehouses for KPI reporting",
            "Prepare executive summaries",
        ],
    }
    context = {
        "full_name": "Sara",
        "field": "Finance",
        "industry": "SaaS",
        "current_job": "Financial Analyst",
        "skillset": "SQL, FP&A, forecasting, Tableau",
    }
    return build_skill_framework(jd, context)["framework"]


def _six_skill_framework():
    """Larger team so expanded planning can propose 4–6 steps."""
    framework = _sample_framework()
    manager = [a for a in framework["agents"] if a.get("type") == "manager" or a.get("id") == "manager"]
    all_skills = [
        a for a in framework["agents"]
        if a.get("type") == "skill" or str(a.get("id", "")).startswith("skill_")
    ]
    preferred = [
        "SQL query",
        "Financial analysis",
        "Statistical modeling",
        "Data visualization",
        "Presentation & storytelling",
        "Written communication",
    ]
    skills = [a for a in all_skills if a.get("skill") in preferred]
    if len(skills) < 6:
        skills = all_skills[:6]
    framework = {**framework, "agents": manager + skills}
    return framework


def _four_skill_framework():
    """Smaller team (4 specialists) so a 3-step plan triggers confirmation."""
    framework = _sample_framework()
    manager = [a for a in framework["agents"] if a.get("type") == "manager" or a.get("id") == "manager"]
    all_skills = [
        a for a in framework["agents"]
        if a.get("type") == "skill" or str(a.get("id", "")).startswith("skill_")
    ]
    preferred = ["SQL query", "Financial analysis", "Statistical modeling", "Presentation & storytelling"]
    skills = [a for a in all_skills if a.get("skill") in preferred]
    if len(skills) < 4:
        skills = all_skills[:4]
    framework = {**framework, "agents": manager + skills}
    return framework


PLAN_CONFIRMATION_PROMPT = (
    "Build a rigorous executive deliverable with methodology and recommendations"
)

EXPANDED_TEAM_PROMPT = (
    "Analyze funnel conversion, build a forecast model, create dashboard charts, "
    "and prepare an executive summary report with recommendations"
)

EU_REG_INVESTMENT_PROMPT = (
    "What is the impact of EU AI regulation on investment in general? "
    "I want to understand implications for portfolio allocation and risk."
)

RECESSION_MACRO_PROMPT = (
    "Given current inflation, unemployment, and yield curve data, forecast the "
    "probability of a recession in the next 12-18 months and suggest defensive positioning"
)


def _investment_skill_agents():
    return [
        {"id": "skill_scenario_planning", "type": "skill", "skill": "Scenario planning"},
        {"id": "skill_forecasting", "type": "skill", "skill": "Forecasting"},
        {"id": "skill_valuation", "type": "skill", "skill": "Valuation"},
        {"id": "skill_financial_modeling", "type": "skill", "skill": "Financial modeling"},
        {"id": "skill_cash_flow", "type": "skill", "skill": "Cash flow"},
        {"id": "skill_investor_reporting", "type": "skill", "skill": "Investor reporting"},
        {"id": "skill_compliance", "type": "skill", "skill": "Compliance & governance"},
        {"id": "skill_business_acumen", "type": "skill", "skill": "Business acumen"},
    ]


def test_tiered_subtask_caps():
    framework = _six_skill_framework()
    skill_agents = [
        a for a in framework["agents"]
        if a.get("type") == "skill" or str(a.get("id", "")).startswith("skill_")
    ]
    assert _max_subtasks(skill_agents, expanded=False) == DEFAULT_MAX_SUBTASKS
    assert _max_subtasks(skill_agents, expanded=True) == min(len(skill_agents), CONFIRMED_MAX_SUBTASKS_CEILING)

    matched = _match_skills_for_request(EXPANDED_TEAM_PROMPT, skill_agents)
    assert _use_expanded_planning_cap(EXPANDED_TEAM_PROMPT, skill_agents, matched, None)
    assert _use_expanded_planning_cap("Thanks", skill_agents, [], "Add compliance review") is True
    assert not _use_expanded_planning_cap("Thanks", skill_agents, [], None)


def test_expanded_planning_allows_more_than_three_subtasks():
    framework = _six_skill_framework()
    skill_agents = [
        a for a in framework["agents"]
        if a.get("type") == "skill" or str(a.get("id", "")).startswith("skill_")
    ]
    expanded_cap = _max_subtasks(skill_agents, expanded=True)
    plan = _manager_decompose_rule(
        EXPANDED_TEAM_PROMPT,
        "Sara",
        framework,
        skill_agents,
        max_subtasks=expanded_cap,
    )
    assert len(plan["subtasks"]) > DEFAULT_MAX_SUBTASKS
    assert len(plan["subtasks"]) <= expanded_cap


def test_default_cap_limits_auto_plan_to_three():
    framework = _six_skill_framework()
    skill_agents = [
        a for a in framework["agents"]
        if a.get("type") == "skill" or str(a.get("id", "")).startswith("skill_")
    ]
    plan = _manager_decompose_rule(
        EXPANDED_TEAM_PROMPT,
        "Sara",
        framework,
        skill_agents,
        max_subtasks=DEFAULT_MAX_SUBTASKS,
    )
    assert len(plan["subtasks"]) <= DEFAULT_MAX_SUBTASKS


def test_approved_plan_executes_all_subtasks(monkeypatch):
    framework = _six_skill_framework()
    skill_agents = [
        a for a in framework["agents"]
        if a.get("type") == "skill" or str(a.get("id", "")).startswith("skill_")
    ]
    expanded_cap = _max_subtasks(skill_agents, expanded=True)
    plan = _manager_decompose_rule(
        EXPANDED_TEAM_PROMPT,
        "Sara",
        framework,
        skill_agents,
        max_subtasks=expanded_cap,
    )
    assert len(plan["subtasks"]) > DEFAULT_MAX_SUBTASKS

    calls = []

    def fake_run_subtask(subtask, agent, *args, **kwargs):
        calls.append(subtask.get("skill"))
        return f"output from {subtask.get('skill')}"

    monkeypatch.setattr("backend.services.chat_orchestrator._run_subtask", fake_run_subtask)
    monkeypatch.setattr("backend.services.chat_orchestrator.cursor_complete", lambda *a, **k: "Final reply")

    context = {"full_name": "Sara", "field": "Finance", "skillset": "SQL, FP&A"}
    result = run_agent_turn(
        context,
        framework,
        EXPANDED_TEAM_PROMPT,
        approved_plan=plan,
    )
    assert len(calls) == len(plan["subtasks"])
    assert result["meta"]["mode"] == "team_task"
    assert result["meta"]["progress_card"]["total"] == len(plan["subtasks"])


def test_subtasks_are_distinct_not_copy_paste():
    framework = _sample_framework()
    skill_agents = [
        a for a in framework["agents"]
        if a.get("type") == "skill" or str(a.get("id", "")).startswith("skill_")
    ]
    user_message = "Analyze the migration funnel and prepare a summary report with recommendations"
    plan = _manager_decompose_rule(user_message, "Sara", framework, skill_agents)
    tasks = [st["task"] for st in plan["subtasks"]]
    assert len(tasks) >= 2
    assert len(set(tasks)) == len(tasks), "Each specialist should get a unique assignment"
    assert plan.get("reasoning")
    for task in tasks:
        assert "Apply " not in task or "Apply rigorous" in task
        assert task != user_message
        assert "MANAGER ASSIGNMENT" not in task


def test_team_mode_for_analytical_requests():
    framework = _sample_framework()
    skill_agents = [a for a in framework["agents"] if a.get("type") == "skill"]
    assert _should_use_team_mode("Analyze funnel drop-off and recommend fixes", skill_agents)
    assert not _should_use_team_mode("What does churn mean?", skill_agents)
    assert not _should_use_team_mode("hi", skill_agents)


def test_direct_answer_skips_delegation():
    assert _is_direct_answer("what date is it today")
    assert _is_direct_answer("hi")
    assert _is_direct_answer("What does churn mean?")
    assert not _is_direct_answer("Analyze funnel drop-off and prepare a summary report")


def test_rule_decompose_assigns_only_relevant_skills():
    framework = _sample_framework()
    skill_agents = [
        a for a in framework["agents"]
        if a.get("type") == "skill" or str(a.get("id", "")).startswith("skill_")
    ]
    plan = _manager_decompose_rule(
        "Write SQL to count weekly active users from the events table",
        "Sara",
        framework,
        skill_agents,
    )
    skills = [st["skill"] for st in plan["subtasks"]]
    assert skills == ["SQL query"]
    assert len(skills) < len(skill_agents)


def test_macro_recession_routes_to_interpretation_not_default_pipeline():
    """Macro + positioning should use business/scenario skills, not stats + board reporting."""
    skill_agents = _investment_skill_agents() + [
        {"id": "skill_statistical", "type": "skill", "skill": "Statistical modeling"},
        {"id": "skill_board", "type": "skill", "skill": "Investor & board reporting"},
    ]
    framework = {"agents": skill_agents, "skill_breakdown": []}
    ranked = _rank_relevant_agents(RECESSION_MACRO_PROMPT, skill_agents, framework, use_llm=False)
    ranked_names = [a["skill"] for a in ranked]
    assert "Business acumen" in ranked_names
    assert "Scenario planning" in ranked_names
    assert "Investor & board reporting" not in ranked_names[:2]
    assert "Statistical modeling" not in ranked_names[:2]

    plan = _manager_decompose_rule(
        RECESSION_MACRO_PROMPT,
        "Richard",
        framework,
        skill_agents,
    )
    skills = [st["skill"] for st in plan["subtasks"]]
    assert skills
    assert any("business" in s.lower() or "scenario" in s.lower() for s in skills)
    assert not any("board reporting" in s.lower() for s in skills)


def test_research_question_skips_irrelevant_modeling_skills():
    skill_agents = _investment_skill_agents()
    framework = {"agents": skill_agents, "skill_breakdown": []}
    ranked = _rank_relevant_agents(EU_REG_INVESTMENT_PROMPT, skill_agents, framework)
    ranked_names = [a["skill"] for a in ranked]
    assert not any(_is_modeling_skill(name) for name in ranked_names)

    plan = _manager_decompose_rule(
        EU_REG_INVESTMENT_PROMPT,
        "Richard",
        framework,
        skill_agents,
    )
    skills = [st["skill"] for st in plan["subtasks"]]
    assert skills
    assert len(skills) <= DEFAULT_MAX_SUBTASKS
    assert not any(_is_modeling_skill(name) for name in skills)
    assert any(
        "compliance" in name.lower() or "business" in name.lower() or "investor" in name.lower()
        for name in skills
    )


def test_rule_decompose_direct_when_no_skills_needed():
    framework = _sample_framework()
    skill_agents = [
        a for a in framework["agents"]
        if a.get("type") == "skill" or str(a.get("id", "")).startswith("skill_")
    ]
    plan = _manager_decompose_rule(
        "Thanks for the help earlier",
        "Sara",
        framework,
        skill_agents,
    )
    assert plan["subtasks"] == []


def test_run_agent_turn_direct_mode_without_api():
    framework = _sample_framework()
    context = {"full_name": "Richard", "field": "Finance", "skillset": "SQL, FP&A"}
    result = run_agent_turn(
        context,
        framework,
        "@Richard Hi Richard, what date is it today?",
    )
    assert result["meta"]["mode"] == "direct"
    assert "Today is" in result["content"]


def test_run_agent_turn_date_does_not_call_cursor(monkeypatch):
    calls = []

    def fail_cursor(*args, **kwargs):
        calls.append(1)
        raise AssertionError("Cursor should not be called for date questions")

    monkeypatch.setattr("backend.services.chat_orchestrator.cursor_chat", fail_cursor)
    framework = _sample_framework()
    context = {"full_name": "Richard", "field": "Finance", "skillset": "SQL, FP&A"}
    result = run_agent_turn(context, framework, "what date is it today?")
    assert not calls
    assert "Today is" in result["content"]


def test_run_agent_turn_team_task_without_api(monkeypatch):
    monkeypatch.setattr("backend.services.chat_orchestrator.cursor_complete", lambda *a, **k: None)
    framework = _four_skill_framework()
    context = {
        "full_name": "Sara",
        "field": "Finance",
        "skillset": "SQL, FP&A",
    }
    result = run_agent_turn(
        context,
        framework,
        PLAN_CONFIRMATION_PROMPT,
    )
    assert result.get("needs_confirmation") is True
    assert result["meta"]["type"] == "plan_proposal"
    card = result["meta"]["progress_card"]
    assert card["manager_plan"]
    outputs = [st["label"] for st in card["subtasks"]]
    assert len(set(outputs)) == len(outputs)


def test_subtask_prompt_uses_assignment_not_full_user_message(monkeypatch):
    captured = []

    def fake_ai(system, user, **kwargs):
        captured.append(user)
        return None

    monkeypatch.setattr("backend.services.chat_orchestrator._llm_complete", fake_ai)

    framework = _sample_framework()
    skill = next(a for a in framework["agents"] if a.get("skill") == "SQL query")
    subtask = {
        "skill": "SQL query",
        "agent_id": skill["id"],
        "task": "[SQL query] Identify metrics and queries needed for funnel analysis only.",
    }
    _run_subtask(subtask, skill, "Sara", "", "")
    assert captured
    prompt = captured[0]
    assert "MANAGER ASSIGNMENT" in prompt
    assert "do not answer the full user request" in prompt.lower() or "your only job" in prompt.lower()
    assert "Identify metrics and queries" in prompt
