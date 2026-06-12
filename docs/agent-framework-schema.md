# Agent Framework Schema

The Studio generates `agent-framework.json` — a multi-agent orchestration spec that simulates how the user works.

## Top-level structure

```json
{
  "version": "1.0",
  "profile_name": "Jane Analyst",
  "field": "Data Analytics",
  "orchestrator": { ... },
  "agents": [ ... ],
  "decision_rules": [ ... ],
  "style_profile": { ... }
}
```

## Orchestrator

Routes incoming work intents to specialized sub-agents:

```json
{
  "role": "work_simulator_orchestrator",
  "description": "Routes tasks through specialized agents",
  "routing_rules": [
    { "intent": "metric_investigation", "agent": "investigator" },
    { "intent": "sql_query", "agent": "sql_analyst" }
  ]
}
```

## Agent definition

Each agent mirrors one aspect of the user's studio performance:

```json
{
  "id": "investigator",
  "role": "Investigation Agent",
  "system_prompt": "You simulate Jane's investigation approach...",
  "triggers": ["revenue drop", "metric anomaly", "investigate"]
}
```

## Decision rules

Chained routing for complex workflows:

```json
{
  "condition": "ambiguous_metric_change",
  "action": "route_to",
  "target": "investigator",
  "then": "sql_analyst"
}
```

## Style profile

Defaults extracted from studio responses:

```json
{
  "communication_tone": "Concise & data-forward",
  "confidence_default": "High",
  "methodology_default": "A/B test"
}
```

## Using the framework

1. Load JSON into your agent runtime (LangGraph, CrewAI, custom orchestrator)
2. Use `orchestrator.routing_rules` for intent classification
3. Inject each agent's `system_prompt` as the role-specific context
4. Pair with `agent-profile.md` for human-readable reference

## Extending

When adding new profession studios, map studio task types to agent roles in `framework_generator.py`.
