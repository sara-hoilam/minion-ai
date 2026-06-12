# Codebase Audit — Minion AI v0.5 (Studio Model)

**Date:** June 2026  
**Status:** Greenfield build (no prior prototype found in workspace)

## Architecture

```
User → Frontend (HTML/JS) → Flask API → SQLite
                                    ↓
                         Studio Tasks → Profile/Framework Generators
                                    ↓
                         agent_outputs/{user_id}/*.md, *.json
                                    ↓
                         Event log (feedback loop)
```

### Request flow

1. **Register/Login** — `POST /api/auth/register`, session via Flask-Login
2. **Background** — `POST /api/profile/background` stores field, skillset, job
3. **Studio** — `POST /api/studio/start` → sequential task submission → artifact generation
4. **Artifacts** — `agent-profile.md` + `agent-framework.json` per completed session
5. **Billing** — Stripe checkout or dev-mode activation

## Reusable vs. rebuilt

| Component | Status |
|-----------|----------|
| NL→SQL live query pipeline | Not in v0.5 — studio captures thinking style instead |
| Multi-model AI | Optional via Anthropic for profile synthesis |
| Data connectors | Deferred — studio is assessment-based |
| Auth + multi-tenant DB | Built (SQLite, upgradeable to Postgres) |
| Event instrumentation | Built from day one |

## Production gaps (v0.5)

- SQLite → Postgres for production multi-tenant
- Secrets in `.env` only; no credential vault yet
- No rate limiting or CSRF tokens
- Stripe webhooks not implemented (manual status update in dev)
- Agent framework is declarative JSON — not yet wired to live agent runtime

## Smallest v0.5 slice

A data analyst signs up → completes background → finishes 5 studio tasks → downloads `.md` profile and multi-agent framework JSON.

## New product model (studio-based)

The platform trains agents by observing users complete take-home-style work tasks, not by connecting data sources. Output artifacts simulate how the person works and can power downstream agent runtimes.
