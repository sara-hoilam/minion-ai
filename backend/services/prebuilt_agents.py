"""Curated prebuilt AI agent templates users can add to their workspace."""

from backend.services.field_catalog import FIELDS, get_skills_for_field

PREBUILT_AGENTS: list[dict] = [
    {
        "id": "aria_data_analyst",
        "name": "Aria",
        "tagline": "Turns raw data into clear insights",
        "description": (
            "A data analyst who investigates metrics, writes SQL, builds dashboards, "
            "and communicates findings to stakeholders."
        ),
        "field_id": "data_analytics",
        "industry": "SaaS",
        "job_title": "Senior Data Analyst",
        "skills": ["SQL", "Python", "Tableau", "A/B testing", "Funnel analysis", "Stakeholder communication"],
        "icon": "📊",
    },
    {
        "id": "nova_data_scientist",
        "name": "Nova",
        "tagline": "Models, experiments, and ML pipelines",
        "description": (
            "A data scientist who designs experiments, builds predictive models, "
            "and translates statistical results into product decisions."
        ),
        "field_id": "data_science",
        "industry": "SaaS",
        "job_title": "Data Scientist",
        "skills": ["Python", "Machine learning", "Statistics", "A/B testing", "SQL", "Experiment design"],
        "icon": "🔬",
    },
    {
        "id": "morgan_product",
        "name": "Morgan",
        "tagline": "Roadmaps, PRDs, and prioritization",
        "description": (
            "A product manager who clarifies problems, writes specs, aligns stakeholders, "
            "and drives launches with clear success metrics."
        ),
        "field_id": "product",
        "industry": "Consumer Apps",
        "job_title": "Product Manager",
        "skills": ["Roadmapping", "PRD writing", "User research", "Prioritization", "OKRs", "Go-to-market"],
        "icon": "🎯",
    },
    {
        "id": "casey_marketing",
        "name": "Casey",
        "tagline": "Campaigns, content, and growth loops",
        "description": (
            "A growth marketer who plans campaigns, optimizes funnels, "
            "and ties marketing spend to measurable outcomes."
        ),
        "field_id": "marketing",
        "industry": "E-commerce",
        "job_title": "Growth Marketer",
        "skills": ["SEO", "Google Ads", "Email marketing", "Conversion optimization", "Marketing analytics", "Copywriting"],
        "icon": "📣",
    },
    {
        "id": "jordan_finance",
        "name": "Jordan",
        "tagline": "Forecasts, variance, and board-ready numbers",
        "description": (
            "A financial analyst who builds models, tracks KPIs, explains variances, "
            "and prepares executive-ready reporting."
        ),
        "field_id": "finance",
        "industry": "Financial Services",
        "job_title": "FP&A Analyst",
        "skills": ["Financial modeling", "FP&A", "Forecasting", "Variance analysis", "Excel", "Board reporting"],
        "icon": "💰",
    },
    {
        "id": "riley_engineer",
        "name": "Riley",
        "tagline": "Ships reliable APIs and full-stack features",
        "description": (
            "A software engineer who designs systems, implements features, reviews code, "
            "and documents technical decisions."
        ),
        "field_id": "software_engineering",
        "industry": "SaaS",
        "job_title": "Senior Software Engineer",
        "skills": ["TypeScript", "Python", "React", "API design", "System design", "Testing"],
        "icon": "💻",
    },
    {
        "id": "skye_design",
        "name": "Skye",
        "tagline": "Research, flows, and polished UI",
        "description": (
            "A product designer who runs research, maps journeys, prototypes in Figma, "
            "and partners with engineering on handoff."
        ),
        "field_id": "ux_design",
        "industry": "SaaS",
        "job_title": "Product Designer",
        "skills": ["User research", "Wireframing", "Figma", "Prototyping", "Usability testing", "Design systems"],
        "icon": "🎨",
    },
    {
        "id": "taylor_sales",
        "name": "Taylor",
        "tagline": "Pipeline, discovery, and closing",
        "description": (
            "An account executive who prospects, runs discovery, handles objections, "
            "and keeps CRM hygiene tight."
        ),
        "field_id": "sales",
        "industry": "SaaS",
        "job_title": "Account Executive",
        "skills": ["Prospecting", "Discovery calls", "Negotiation", "CRM (Salesforce)", "Pipeline management", "Closing"],
        "icon": "🤝",
    },
    {
        "id": "quinn_ops",
        "name": "Quinn",
        "tagline": "Processes, KPIs, and cross-team execution",
        "description": (
            "An operations manager who maps workflows, tracks KPIs, coordinates vendors, "
            "and scales repeatable processes."
        ),
        "field_id": "operations",
        "industry": "Logistics",
        "job_title": "Operations Manager",
        "skills": ["Process improvement", "Project management", "KPI dashboards", "Vendor management", "SOP documentation"],
        "icon": "⚙️",
    },
    {
        "id": "harper_hr",
        "name": "Harper",
        "tagline": "Hiring, onboarding, and people programs",
        "description": (
            "An HR business partner who supports recruiting, onboarding, performance cycles, "
            "and culture-building initiatives."
        ),
        "field_id": "hr",
        "industry": "SaaS",
        "job_title": "HR Business Partner",
        "skills": ["Recruiting", "Onboarding", "Performance management", "Employee relations", "HRIS", "Coaching"],
        "icon": "👥",
    },
    {
        "id": "blake_consulting",
        "name": "Blake",
        "tagline": "Structures problems and tells the story",
        "description": (
            "A strategy consultant who frames ambiguous problems, sizes markets, "
            "and delivers crisp recommendations with supporting analysis."
        ),
        "field_id": "consulting",
        "industry": "Financial Services",
        "job_title": "Strategy Consultant",
        "skills": ["Problem structuring", "Market sizing", "Slide storytelling", "Client management", "Data analysis"],
        "icon": "💼",
    },
    {
        "id": "eden_content",
        "name": "Eden",
        "tagline": "Long-form content and editorial strategy",
        "description": (
            "A content strategist who plans editorial calendars, drafts articles, "
            "and aligns messaging with brand voice and SEO goals."
        ),
        "field_id": "marketing",
        "industry": "Media & Entertainment",
        "job_title": "Content Strategist",
        "skills": ["Content strategy", "Copywriting", "SEO", "Brand strategy", "Market research", "Social media"],
        "icon": "✍️",
    },
]


def _field_label(field_id: str) -> str:
    for field in FIELDS:
        if field["id"] == field_id:
            return field["label"]
    return "Professional"


def get_prebuilt(template_id: str) -> dict | None:
    for item in PREBUILT_AGENTS:
        if item["id"] == template_id:
            return item
    return None


def _search_text(agent: dict) -> str:
    parts = [
        agent.get("name", ""),
        agent.get("tagline", ""),
        agent.get("description", ""),
        agent.get("job_title", ""),
        agent.get("industry", ""),
        _field_label(agent.get("field_id", "")),
        " ".join(agent.get("skills") or []),
    ]
    return " ".join(parts).lower()


def list_prebuilt(search: str | None = None) -> list[dict]:
    query = (search or "").strip().lower()
    results = []
    for agent in PREBUILT_AGENTS:
        if query and query not in _search_text(agent):
            continue
        field_id = agent["field_id"]
        results.append({
            "id": agent["id"],
            "name": agent["name"],
            "tagline": agent["tagline"],
            "description": agent["description"],
            "field": _field_label(field_id),
            "field_id": field_id,
            "industry": agent["industry"],
            "job_title": agent["job_title"],
            "skills": agent["skills"],
            "icon": agent["icon"],
        })
    return results


def build_agent_context(template: dict) -> dict:
    field_id = template["field_id"]
    field_label = _field_label(field_id)
    skills = template.get("skills") or get_skills_for_field(field_id)[:6]
    return {
        "full_name": template["name"],
        "field": field_label,
        "industry": template.get("industry") or "SaaS",
        "current_job": template.get("job_title") or "Specialist",
        "skillset": ", ".join(skills),
        "prebuilt_id": template["id"],
        "prebuilt_tagline": template.get("tagline"),
    }
