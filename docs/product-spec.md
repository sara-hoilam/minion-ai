# Product Spec — Minion AI v0.5 (Studio Model)

**Version:** 0.5  
**Date:** June 2026  
**Status:** Ready for user testing

## One-liner

A platform where professionals train a personal AI agent by completing a Studio assessment — like a take-home test — that produces an agent profile and multi-agent framework simulating how they work.

## Buyer persona (hypothesis — validate in interviews)

**Primary:** Data analyst at small-to-mid SaaS or e-commerce (2–8 years experience)

- Uses SQL daily, reports to product/marketing stakeholders
- Wants AI help but ChatGPT doesn't know their company's metrics, style, or methodology preferences
- Would pay $39–79/mo for an agent that works *like them*, not generic

## Core workflows (Studio-validated)

1. **Investigate metric changes** — structured step order when something drops
2. **Write and explain SQL** — recurring metrics (WAU, funnel, revenue)
3. **Interpret and recommend** — funnel/cohort results → product actions
4. **Executive communication** — weekly KPI summaries
5. **Choose methodology** — A/B vs observational for feature impact

## What ChatGPT fails at (our wedge)

- Doesn't remember your investigation order or communication style
- Can't simulate *your* SQL conventions and assumptions
- No persistent multi-agent routing matching how you delegate mental sub-tasks
- Generic advice vs. your calibrated confidence levels

## v0.5 scope

**In:**
- Sign up, background capture, Data Analyst Studio (5 tasks)
- Agent profile `.md` + framework `.json` generation
- Event logging, Stripe/dev-mode billing

**Out:**
- Live database connections
- Marketplace, template publishing
- Multiple profession studios (architecture ready, only DA shipped)
- Runtime agent execution (artifacts are the output for now)

## Pricing

- Entry: $49/mo (configurable via Stripe)
- Optional setup fee: deferred to v1

## Success metrics (90 days)

- 8/10 test users complete Studio and download artifacts
- 3–5 paying customers, $200–500 MRR
- Median Studio completion time < 35 minutes
- <20% drop-off after task 2

## Decision gate

If <30% of interviewed analysts would pay $50/mo after seeing Studio output, narrow to a sub-persona (e.g. e-commerce analysts only) before adding professions.
