"""Field, industry, role, and skill options for background onboarding."""

FIELDS = [
    {"id": "data_analytics", "label": "Data Analytics", "icon": "📊"},
    {"id": "data_science", "label": "Data Science", "icon": "🔬"},
    {"id": "product", "label": "Product Management", "icon": "🎯"},
    {"id": "marketing", "label": "Marketing", "icon": "📣"},
    {"id": "finance", "label": "Finance", "icon": "💰"},
    {"id": "software_engineering", "label": "Software Engineering", "icon": "💻"},
    {"id": "ux_design", "label": "UX / Product Design", "icon": "🎨"},
    {"id": "sales", "label": "Sales", "icon": "🤝"},
    {"id": "operations", "label": "Operations", "icon": "⚙️"},
    {"id": "hr", "label": "People / HR", "icon": "👥"},
    {"id": "consulting", "label": "Consulting", "icon": "💼"},
    {"id": "other", "label": "Other", "icon": "✦"},
]

INDUSTRIES = [
    "E-commerce",
    "SaaS",
    "Financial Services",
    "Healthcare",
    "Retail",
    "Media & Entertainment",
    "Education",
    "Manufacturing",
    "Logistics",
    "Real Estate",
    "Non-profit",
    "Government",
    "Energy",
    "Travel & Hospitality",
    "Consumer Apps",
    "Other",
]

ROLES_BY_FIELD: dict[str, list[str]] = {
    "data_analytics": [
        "Data Analyst",
        "Senior Data Analyst",
        "Analytics Engineer",
        "Business Intelligence Analyst",
        "Growth Analyst",
        "Product Analyst",
    ],
    "data_science": [
        "Data Scientist",
        "Senior Data Scientist",
        "ML Engineer",
        "Research Scientist",
        "Applied Scientist",
    ],
    "product": [
        "Product Manager",
        "Senior Product Manager",
        "Product Owner",
        "Group Product Manager",
        "Technical Product Manager",
    ],
    "marketing": [
        "Marketing Manager",
        "Growth Marketer",
        "Content Marketer",
        "Performance Marketer",
        "Brand Manager",
        "Marketing Analyst",
    ],
    "finance": [
        "Financial Analyst",
        "FP&A Analyst",
        "Controller",
        "Accountant",
        "Investment Analyst",
    ],
    "software_engineering": [
        "Software Engineer",
        "Senior Software Engineer",
        "Full-stack Engineer",
        "Backend Engineer",
        "Frontend Engineer",
        "Engineering Manager",
    ],
    "ux_design": [
        "UX Designer",
        "Product Designer",
        "UI Designer",
        "Design Lead",
        "UX Researcher",
    ],
    "sales": [
        "Account Executive",
        "Sales Development Rep",
        "Customer Success Manager",
        "Sales Manager",
        "Solutions Consultant",
    ],
    "operations": [
        "Operations Manager",
        "Program Manager",
        "Project Manager",
        "Chief of Staff",
        "Business Operations Analyst",
    ],
    "hr": [
        "HR Business Partner",
        "Recruiter",
        "People Operations",
        "Talent Acquisition",
        "Learning & Development",
    ],
    "consulting": [
        "Management Consultant",
        "Strategy Consultant",
        "Implementation Consultant",
        "Associate Consultant",
    ],
    "other": [
        "Individual Contributor",
        "Team Lead",
        "Manager",
        "Director",
        "Founder / Owner",
    ],
}

SKILLS_BY_FIELD: dict[str, list[str]] = {
    "data_analytics": [
        "SQL", "Python", "R", "Excel", "Tableau", "Looker", "Power BI",
        "A/B testing", "Funnel analysis", "Cohort analysis", "Dashboard design",
        "Statistical analysis", "Data modeling", "ETL", "dbt", "Snowflake",
        "BigQuery", "Stakeholder communication", "Experiment design", "KPI tracking",
    ],
    "data_science": [
        "Python", "R", "Machine learning", "Deep learning", "Statistics",
        "Feature engineering", "Model deployment", "MLOps", "NLP", "Computer vision",
        "Time series", "A/B testing", "SQL", "Spark", "TensorFlow", "PyTorch",
        "Experiment design", "Research papers", "Causal inference", "Bayesian methods",
    ],
    "product": [
        "Roadmapping", "User research", "Prioritization", "PRD writing",
        "Stakeholder management", "A/B testing", "Metrics definition", "Go-to-market",
        "Competitive analysis", "Agile / Scrum", "Wireframing", "Launch planning",
        "Customer interviews", "OKRs", "Backlog grooming", "Cross-functional leadership",
    ],
    "marketing": [
        "SEO", "Content strategy", "Google Ads", "Meta Ads", "Email marketing",
        "Brand strategy", "Copywriting", "Marketing analytics", "CRM", "HubSpot",
        "Social media", "Influencer marketing", "Product marketing", "Demand gen",
        "Conversion optimization", "Market research", "Campaign planning", "Attribution",
    ],
    "finance": [
        "Financial modeling", "FP&A", "Budgeting", "Forecasting", "Variance analysis",
        "Excel", "Accounting", "P&L management", "Cash flow", "Valuation",
        "Due diligence", "Audit", "Compliance", "SAP", "QuickBooks",
        "Investor reporting", "Cost analysis", "Scenario planning", "Board reporting",
    ],
    "software_engineering": [
        "JavaScript", "TypeScript", "Python", "Java", "Go", "React", "Node.js",
        "API design", "System design", "AWS", "Docker", "Kubernetes", "CI/CD",
        "Testing", "Git", "SQL", "Microservices", "Performance optimization",
        "Code review", "Technical documentation", "Security best practices",
    ],
    "ux_design": [
        "User research", "Wireframing", "Prototyping", "Figma", "Design systems",
        "Usability testing", "Information architecture", "Interaction design",
        "Visual design", "Accessibility", "User flows", "Journey mapping",
        "Design critique", "Handoff to engineering", "A/B test design", "Heuristic evaluation",
    ],
    "sales": [
        "Prospecting", "Cold outreach", "Discovery calls", "Demo delivery",
        "Negotiation", "CRM (Salesforce)", "Pipeline management", "Account planning",
        "Objection handling", "Closing", "Upselling", "Cross-selling",
        "Relationship building", "Sales forecasting", "Territory planning", "Partnerships",
    ],
    "operations": [
        "Process improvement", "Project management", "Vendor management",
        "Budget tracking", "KPI dashboards", "SOP documentation", "Risk management",
        "Supply chain", "Lean / Six Sigma", "Change management", "Resource planning",
        "Cross-team coordination", "Operational analytics", "Compliance", "Scaling ops",
    ],
    "hr": [
        "Recruiting", "Interviewing", "Onboarding", "Performance management",
        "Compensation", "Employee relations", "HRIS", "DEI programs",
        "Learning programs", "Policy development", "Workforce planning",
        "Employer branding", "Benefits administration", "Culture building", "Coaching",
    ],
    "consulting": [
        "Problem structuring", "Client management", "Slide storytelling",
        "Market sizing", "Competitive analysis", "Workshop facilitation",
        "Change management", "Stakeholder interviews", "Business case development",
        "Process mapping", "Implementation planning", "Executive communication",
        "Data analysis", "Industry research", "Project leadership", "Frameworks (MECE)",
    ],
    "other": [
        "Communication", "Project management", "Data analysis", "Research",
        "Writing", "Presentation", "Leadership", "Problem solving",
        "Cross-functional collaboration", "Strategic planning", "Customer focus",
        "Process improvement", "Documentation", "Training others", "Adaptability",
    ],
}


def resolve_field_id(field_label: str) -> str:
    key = (field_label or "").strip().lower()
    for field in FIELDS:
        if field["id"] == key or field["label"].lower() == key:
            return field["id"]
    for field in FIELDS:
        if field["id"] in key or key in field["label"].lower():
            return field["id"]
    return "other"


def get_roles_for_field(field_id: str) -> list[str]:
    return ROLES_BY_FIELD.get(field_id, ROLES_BY_FIELD["other"])


def get_skills_for_field(field_id: str) -> list[str]:
    return SKILLS_BY_FIELD.get(field_id, SKILLS_BY_FIELD["other"])


def catalog_payload() -> dict:
    return {
        "fields": FIELDS,
        "industries": INDUSTRIES,
        "roles_by_field": ROLES_BY_FIELD,
        "skills_by_field": SKILLS_BY_FIELD,
    }
