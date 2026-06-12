"""Generate multi-agent framework JSON from studio submissions."""

import json


def _extract_steps(text: str) -> list[str]:
    if not text:
        return []
    return [line.strip() for line in str(text).split("\n") if line.strip()]


def generate_agent_framework(profile: dict, responses: list) -> dict:
    name = profile.get("full_name") or "User"
    field = profile.get("field") or "data_analyst"

    by_id = {r.get("task_id"): r.get("response_data", {}) for r in responses}

    inv = by_id.get("investigation_scenario", {})
    sql = by_id.get("sql_challenge", {})
    interpret = by_id.get("interpret_results", {})
    comm = by_id.get("stakeholder_communication", {})
    method = by_id.get("methodology_choice", {})

    investigation_steps = _extract_steps(inv.get("steps", "")) if inv else []

    assessed_tasks = [k for k, v in by_id.items() if v]

    framework = {
        "version": "1.0",
        "profile_name": name,
        "field": field,
        "training_progress": {
            "tasks_assessed": len(assessed_tasks),
            "agents_active": len(assessed_tasks),
        },
        "orchestrator": {
            "role": "work_simulator_orchestrator",
            "description": f"Routes tasks through specialized agents that simulate how {name} works.",
            "routing_rules": [
                {"intent": "metric_investigation", "agent": "investigator"},
                {"intent": "sql_query", "agent": "sql_analyst"},
                {"intent": "interpret_results", "agent": "interpreter"},
                {"intent": "stakeholder_update", "agent": "communicator"},
                {"intent": "methodology_decision", "agent": "methodologist"},
            ],
        },
        "agents": [
            {
                "id": "investigator",
                "role": "Investigation Agent",
                "system_prompt": (
                    f"You simulate {name}'s investigation approach. "
                    f"When metrics change unexpectedly, follow this step order:\n"
                    + "\n".join(f"{i+1}. {s}" for i, s in enumerate(investigation_steps))
                    + f"\n\nReasoning style: {inv.get('reasoning', '')}"
                ),
                "triggers": ["revenue drop", "metric anomaly", "why did", "investigate"],
            },
            {
                "id": "sql_analyst",
                "role": "SQL Agent",
                "system_prompt": (
                    f"You write SQL the way {name} does.\n"
                    f"Reference style query:\n```sql\n{sql.get('sql', '')}\n```\n"
                    f"Assumptions: {sql.get('approach_notes', '')}"
                ),
                "triggers": ["write sql", "query", "calculate", "pull data"],
                "preferred_dialect": "standard_sql",
            },
            {
                "id": "interpreter",
                "role": "Interpretation Agent",
                "system_prompt": (
                    f"You interpret data like {name}.\n"
                    f"Takeaway pattern: {interpret.get('takeaway', '')}\n"
                    f"Recommendation style: {interpret.get('recommendation', '')}\n"
                    f"Confidence calibration: {interpret.get('confidence', 'Medium')}"
                ),
                "triggers": ["what does this mean", "interpret", "so what", "recommend"],
            },
            {
                "id": "communicator",
                "role": "Communication Agent",
                "system_prompt": (
                    f"You communicate like {name} to stakeholders.\n"
                    f"Structure: {comm.get('structure', '')}\n"
                    f"Issue flagging: {comm.get('issue_flagging', '')}\n"
                    f"Tone: {comm.get('tone', 'Balanced')}"
                ),
                "triggers": ["email", "summary", "executive", "report", "update"],
            },
            {
                "id": "methodologist",
                "role": "Methodology Agent",
                "system_prompt": (
                    f"You choose analytical methods like {name}.\n"
                    f"Preferred method: {method.get('method', '')}\n"
                    f"Rationale: {method.get('rationale', '')}\n"
                    f"Data requirements: {method.get('data_needed', '')}"
                ),
                "triggers": ["a/b test", "causal", "methodology", "how to measure impact"],
            },
        ],
        "decision_rules": [
            {
                "condition": "ambiguous_metric_change",
                "action": "route_to",
                "target": "investigator",
                "then": "sql_analyst",
            },
            {
                "condition": "results_ready",
                "action": "route_to",
                "target": "interpreter",
                "then": "communicator",
            },
            {
                "condition": "impact_measurement_request",
                "action": "route_to",
                "target": "methodologist",
            },
        ],
        "style_profile": {
            "communication_tone": comm.get("tone", "Balanced"),
            "confidence_default": interpret.get("confidence", "Medium"),
            "methodology_default": method.get("method", "A/B test"),
        },
    }
    return framework


def framework_to_json(framework: dict) -> str:
    return json.dumps(framework, indent=2)
