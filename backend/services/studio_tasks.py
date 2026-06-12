"""Studio task definitions — take-home-style assessments per profession."""

DATA_ANALYST_STUDIO = {
    "id": "data_analyst",
    "name": "Data Analyst Studio",
    "description": "Complete realistic analyst tasks so we can learn how you investigate, query, and communicate.",
    "estimated_minutes": 25,
    "tasks": [
        {
            "id": "investigation_scenario",
            "type": "scenario",
            "title": "Investigation: Revenue Drop",
            "prompt": (
                "Weekly revenue for your e-commerce company dropped 15% compared to the prior week. "
                "The product team says no major releases shipped. Marketing spend was flat."
            ),
            "instructions": (
                "Walk through how you would investigate this. List your first 3–5 steps in order, "
                "and explain why each step matters."
            ),
            "fields": [
                {"name": "steps", "type": "ordered_list", "label": "Investigation steps (one per line, in order)", "min_items": 3},
                {"name": "reasoning", "type": "textarea", "label": "Why this order? What are you ruling out first?"},
            ],
        },
        {
            "id": "sql_challenge",
            "type": "sql_challenge",
            "title": "SQL: Weekly Active Users",
            "prompt": "You have the following schema:",
            "schema": (
                "events(user_id INT, event_name VARCHAR, event_timestamp TIMESTAMP)\n"
                "users(user_id INT, signup_date DATE, country VARCHAR)"
            ),
            "instructions": (
                "Write a SQL query to calculate weekly active users (distinct users with any event) "
                "for the last 8 weeks. Include week start date and WAU count."
            ),
            "fields": [
                {"name": "sql", "type": "code", "label": "Your SQL query", "language": "sql"},
                {"name": "approach_notes", "type": "textarea", "label": "Any assumptions or edge cases you considered?"},
            ],
        },
        {
            "id": "interpret_results",
            "type": "interpretation",
            "title": "Interpret: Funnel Analysis",
            "prompt": (
                "A funnel report shows: Landing page 100k → Signup 12k (12%) → "
                "Activation 4.8k (40% of signups) → Paid 960 (20% of activations). "
                "Week-over-week, signup rate is flat but activation dropped from 48% to 40%."
            ),
            "instructions": "What is your takeaway, and what would you recommend to the product team?",
            "fields": [
                {"name": "takeaway", "type": "textarea", "label": "Your interpretation"},
                {"name": "recommendation", "type": "textarea", "label": "Recommended next steps"},
                {"name": "confidence", "type": "select", "label": "Confidence in this diagnosis", "options": ["Low", "Medium", "High"]},
            ],
        },
        {
            "id": "stakeholder_communication",
            "type": "communication",
            "title": "Communicate: Executive Summary",
            "prompt": (
                "Your VP asks for a weekly KPI email every Monday covering growth, retention, and revenue."
            ),
            "instructions": (
                "Outline the structure of your weekly email. What metrics appear first, "
                "how do you flag issues, and what tone do you use?"
            ),
            "fields": [
                {"name": "structure", "type": "textarea", "label": "Email structure (sections and metrics)"},
                {"name": "issue_flagging", "type": "textarea", "label": "How do you flag problems vs. wins?"},
                {"name": "tone", "type": "select", "label": "Primary tone", "options": ["Concise & data-forward", "Narrative & contextual", "Balanced"]},
            ],
        },
        {
            "id": "methodology_choice",
            "type": "methodology",
            "title": "Methodology: Feature Impact",
            "prompt": (
                "Product launched a new onboarding flow. You need to estimate its impact on 7-day retention."
            ),
            "instructions": (
                "Choose your approach and explain tradeoffs. Would you run an A/B test, "
                "use diff-in-diff, or something else?"
            ),
            "fields": [
                {
                    "name": "method",
                    "type": "select",
                    "label": "Primary method",
                    "options": ["A/B test", "Diff-in-diff", "Before/after comparison", "Propensity matching", "Other"],
                },
                {"name": "rationale", "type": "textarea", "label": "Why this method? What are the risks?"},
                {"name": "data_needed", "type": "textarea", "label": "What data would you need before starting?"},
            ],
        },
    ],
}

STUDIO_TEMPLATES = {
    "data_analyst": DATA_ANALYST_STUDIO,
    "data science": DATA_ANALYST_STUDIO,
    "analytics": DATA_ANALYST_STUDIO,
    "data_analytics": DATA_ANALYST_STUDIO,
    "marketing": DATA_ANALYST_STUDIO,
    "product": DATA_ANALYST_STUDIO,
    "finance": DATA_ANALYST_STUDIO,
    "software_engineering": DATA_ANALYST_STUDIO,
    "ux_design": DATA_ANALYST_STUDIO,
    "sales": DATA_ANALYST_STUDIO,
    "operations": DATA_ANALYST_STUDIO,
    "hr": DATA_ANALYST_STUDIO,
    "consulting": DATA_ANALYST_STUDIO,
}


def resolve_studio_for_field(field: str) -> dict:
    key = (field or "").strip().lower()
    for template_key, template in STUDIO_TEMPLATES.items():
        if template_key in key or key in template_key:
            return template
    return DATA_ANALYST_STUDIO


def get_task(template: dict, task_index: int) -> dict | None:
    tasks = template.get("tasks", [])
    if 0 <= task_index < len(tasks):
        return tasks[task_index]
    return None
