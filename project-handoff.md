# Project Handoff — AI Agent Builder for Non-Technical Professionals

**Founder:** Sara Chang
**Date:** May 2026
**Status:** Pre-build. Existing analytics agent prototype to be productized.

---

## The Idea (One-Sentence Version)

A no-code platform that lets non-technical professionals turn their work expertise into a personal AI agent — starting with data analysts, evolving into a template marketplace where professionals can publish and license their agents.

## Why This Idea, For Sara Specifically

- 5+ years data science across MMM, retail analytics, CRM, product analytics
- Already built a working analytics agent prototype (analytics agent reads databases and writes SQL)
- Currently Head of Audience Intelligence at The Bay; non-compete blocks news/media space but everything else open
- 4-day work week, fully remote — real building bandwidth on Fri-Sun + flex weekdays
- Strong domain instinct that most knowledge workers want AI help but can't build agents themselves
- Personally motivated by "building a digital version of myself"

## What This Is NOT

- Not a clone-yourself-for-hire marketplace (Delphi already owns adjacent space; structural problems with clones-for-execution)
- Not MMM-as-an-API (too narrow, requires constant model maintenance, Sara doesn't want grindy modeling work)
- Not an agent-services-for-agents play (Sara wants to build a human-facing product first)
- Not infrastructure for the agent economy (crowded by Coinbase/AWS/Google/Cloudflare/Stripe)

## The Competitive Landscape

**Adjacent products to be aware of:**

- **Delphi.ai** — clones experts for conversation/coaching, not for work execution. Different use case.
- **MindStudio, Relevance AI, Lindy, Gumloop, n8n, Stack AI, Vellum** — agent builders skewed toward technical or semi-technical users. None nails the truly non-technical pro.
- **MindBank Ai, Persona Studios** — personal AI clones, conversational focus
- **11x, Artisan, Lindy AI employees** — vendor-built standardized AI workers, not user-trained
- **ADP Marketplace, Coinbase Agentic.market** — distribution platforms for vendor-built agents
- **Mem0, Letta, Zep** — memory infrastructure (might be a dependency)
- **MemoClaw** — already does memory-for-agents on x402 (proof of pricing model)

**The wedge:** No one has built an agent builder specifically for non-technical professionals with deep vertical focus and opinionated defaults. Existing products are either too flexible (require technical skill) or too rigid (don't capture user's specific workflow).

## The Strategy

### Adaptation 1 → 2 sequencing

**Year 1: Adaptation 1.** A no-code agent builder targeting ONE profession (data analysts). Users sign up, complete structured onboarding (case study questions, workflow Q&A, document upload, data source connection), get back a working AI agent in <30 minutes. They use it for their daily work; we capture every interaction as training signal.

**Year 2: Adaptation 2.** Once we have ~500-1000 active users with high-quality agents, activate marketplace features. Users can publish their agent templates; other professionals or companies license them with revenue share. We become the "Shopify for professional AI agents."

### The Feedback Loop (the real moat)

Every user interaction with their agent generates training signal:
- Queries asked (intent patterns)
- Outputs accepted/rejected/edited (quality signal)
- Tools used most/least (workflow signal)
- Domain-specific terminology and conventions

Over time:
- Onboarding gets shorter (we learn what defaults work for which profession)
- Agent quality improves (we learn what makes a "good" data analyst agent)
- Vertical templates auto-generate from user patterns
- Cold-start gets faster for new users in same profession

This data advantage is impossible to replicate without similar user base. Must be instrumented from day one.

## The Three Non-Negotiable Commitments

1. **Opinionated, not flexible.** Pre-built templates, hardcoded defaults, limited choices. Users fill in blanks; they don't architect anything. If we drift toward a flexible canvas, we lose to MindStudio.

2. **One profession at a time.** Start with data analysts. Expand to marketing managers / CRM specialists / accountants only after profession #1 has paying customers. Resist horizontal expansion.

3. **Marketplace ships late.** Adaptation 2 is a year-2 feature, not a year-1 foundation. Building marketplace infra before having users is the classic platform-startup failure mode.

## 90-Day Plan

### Phase 1: Validate (weeks 1-3)
- Interview 10-15 data analysts at small-to-mid SaaS/e-commerce companies
- Show them the existing analytics agent prototype
- Test the core question: "Would you pay $50/mo for a tool that turned your work knowledge into a custom AI assistant?"
- Output: one-page product spec with confirmed buyer persona and workflows

### Phase 2: Build v0.5 onboarding (weeks 3-6)
- Take existing analytics agent code and templatize it
- Build the structured onboarding flow (the actual product)
  - Structured questions about their job
  - Document upload (past reports, sample queries, methodology docs)
  - One data source connection (probably PostgreSQL or Snowflake — confirm from interviews)
  - Generates configured agent at the end
  - Lets them test in chat
- Instrument logging for the feedback loop from day one

### Phase 3: Iterate until 8/10 users succeed (weeks 6-10)
- Fix drop-off points obsessively
- Add Stripe billing in week 9
- Price at $39-79/mo entry tier
- Start charging real money

### Phase 4: First 5 paying customers (weeks 10-12)
- Target $200-500 MRR
- Document what's working, what's not
- Decide next 90-day priorities (likely: refine product, add second profession, or improve feedback loop)

## Monetization Model

**Year 1:**
- Subscription per user: $39-79/mo entry, $99-149/mo pro
- One-time setup/onboarding fee ($199-499) optional, helps cash flow
- Team plans ($199-499/mo) once companies want multiple seats

**Year 2 (with marketplace):**
- Template sales/licensing — 20-30% platform cut
- Featured placement for creators
- Verified pro tier subscription
- API access for agent buyers (x402 payment rails)

**Target trajectory (solo, bootstrapped):**
- Month 3: 3-5 customers, $300-500 MRR
- Month 6: 10-15 customers, $2-5K MRR
- Month 12: 30-50 customers, $10-25K MRR, decision point on leaving day job
- Month 18: Second profession launched, $25-50K MRR, marketplace beta

## Existing Assets

- Working analytics agent prototype with:
  - Frontend in HTML/CSS/JS
  - Python Flask backend
  - Multi-model AI integration (Grok, Claude, Gemini)
  - Data source connectors (AWS S3, Databricks, local files)
  - Natural language query → SQL → results pipeline
  - Interactive visualizations
- Repository structure prepared for multiple agents (copywriting, marketing, labour planning, product planning, CRM — all "coming soon")

## What Sara Has to Resist

- **Adding more agents to the README before the analytics agent has paying customers.** The "coming soon" list is a distraction.
- **Building the marketplace early.** Year 2 feature.
- **Making it more flexible to attract more user types.** The opposite of what wins.
- **Vibe-coding new features without customer feedback.** Pattern from past projects (Remi Planner, PDFGodWork) that didn't lead to revenue.
- **Skipping customer interviews to start coding.** The single highest-leverage activity.

## What Sara Should Do in Claude Code (Next Steps)

When we open Claude Code, the planned sequence:

1. **Full read of existing analytics agent codebase** — architecture, AI integration, data flow, state of production-readiness
2. **Identify reusable vs. needs-rebuilding components** for multi-tenant SaaS
3. **Sketch the onboarding flow as a separate layer** on top of templatized agent
4. **Define the smallest viable v0.5** — what ships in 3 weeks for first user tests
5. **Plan the instrumentation/logging architecture** for the feedback-loop moat

Explicitly NOT in scope yet:
- Marketplace features
- Template publishing system
- Multiple profession support
- Personal style training / fine-tuning
- x402 / agent-payment integration

## Key Risks to Track

1. **Agent isn't actually useful** — onboarding ships, users complete it, agent feels mid. Mitigation: deep vertical focus on workflows where ChatGPT fails today.
2. **Customer acquisition too expensive** — can't acquire without paid ads, LTV doesn't support. Mitigation: network-led growth for v1, content marketing in parallel.
3. **Feature creep / horizontal drift** — gradually building for everyone, losing focus. Mitigation: hardcoded discipline of one profession, one buyer.
4. **Quality control on user-generated agents** — agents users build are bad, brand suffers. Mitigation: heavy opinionated defaults, prevent users from building bad agents in the first place.
5. **Non-compete or employment IP issues** — must verify The Bay's contract allows this build, and the build doesn't touch news/media/audience-intelligence space.

## The Honest Pre-Mortem

Most likely failure: Sara builds a polished onboarding flow and a templated analytics agent, but the agent isn't 10x better than ChatGPT-with-uploaded-data for the data analyst's actual job. Users complete onboarding, try it for a week, churn. The lesson would be that the feedback-loop moat requires the agent to be useful *first* — you can't bootstrap the moat without initial product-market fit.

Second most likely failure: Sara gets distracted by the marketplace vision and starts building Adaptation 2 features before Adaptation 1 has paying customers. The product becomes generic, loses focus, runs out of energy before achieving traction.

Mitigation for both: ruthless focus on making the v0.5 analytics agent dramatically more useful than alternatives for one specific buyer, before adding any other surface area.

---

**Status when moving to Claude Code:** Ready to read codebase, plan v0.5, build with focus on one profession (data analysts) and the structured onboarding flow that captures their work knowledge.
