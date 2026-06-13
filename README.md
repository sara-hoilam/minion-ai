# Minion AI

Train a personal AI agent by completing a **Studio assessment** — like an online take-home test. The platform learns how you investigate, analyze, and communicate, then generates:

- **`agent-profile.md`** — how you think and work
- **`agent-framework.json`** — multi-agent framework that simulates your workflow

## Quick start

```bash
cd "Minion AI"
py -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env
py run.py
```

Open http://localhost:5000

**Auth:** Login uses **Supabase Auth** when `SUPABASE_ANON_KEY` is set (recommended for production). Without it, the app falls back to local password auth (used in tests). Set `DISABLE_AUTH=true` for dev auto-login as `demo@minion.ai` / `demo`.

### Supabase Auth setup

1. In [Supabase Dashboard](https://supabase.com/dashboard) → your project → **Project Settings → API**, copy:
   - **anon public** key → `SUPABASE_ANON_KEY`
   - **service_role** key → `SUPABASE_SERVICE_ROLE_KEY` (already used for Storage)
2. Add to `.env` (see `.env.example`).
3. Run migration `supabase/migrations/20260615160000_supabase_auth_user_link.sql` (SQL editor or `supabase db push`).
4. **Authentication → URL configuration**: set **Site URL** to your `APP_URL` (e.g. `http://localhost:5000`).
5. Optional: disable **Confirm email** under Authentication → Providers → Email for faster local testing.
6. Restart the Flask app and sign up / log in — accounts are created in Supabase Auth and linked to the app `users` table.

## User flow

1. **Sign up** and log in (optionally upload resume to auto-fill background)
2. **Background** — field, skillset, current job, experience
3. **Studio** — complete work tasks (agent created after the **first** task)
4. **Results** — download your agent profile and multi-agent framework; continue training for more tasks
5. **Subscribe** — Stripe checkout (or dev-mode activation without keys)

If you have an existing `minion.db` from an older version, delete it and restart so the schema updates.

## Optional: AI-enhanced profiles

Set `ANTHROPIC_API_KEY` in `.env` to synthesize richer agent profiles via Claude. Without it, rule-based generation still works.

## Project structure

```
backend/
  app.py              Flask app
  models.py           User, StudioSession, TaskResponse, Events
  routes/             auth, profile, studio, events, billing
  services/           studio tasks, profile/framework generators
frontend/             HTML/CSS/JS SPA
docs/                 audit, studio design, product spec, interviews
agent_outputs/        generated .md and .json per user (gitignored)
```

## Docs

- [Studio design](docs/studio-design.md)
- [Product spec](docs/product-spec.md)
- [Interview guide](docs/interview-guide.md)
- [Codebase audit](docs/codebase-audit.md)

## Stripe

Live products are configured in Stripe Dashboard. The app uses **Price IDs** (`price_...`) for Checkout — not Product IDs (`prod_...`).

Set these in Render (or `.env` locally):

| Variable | Required | Notes |
|----------|----------|--------|
| `STRIPE_SECRET_KEY` | Yes (live) | `sk_live_...` — **never commit**; set in Render only |
| `STRIPE_PUBLISHABLE_KEY` | Yes | `pk_live_...` |
| `STRIPE_WEBHOOK_SECRET` | Yes (live) | `whsec_...` from webhook endpoint |
| `STRIPE_PRICE_STARTER` | Yes | `price_1ThY9w377xE4C0OxJPby2yLm` ($10/mo) |
| `STRIPE_PRICE_GROWTH` | Yes | `price_1ThYB0377xE4C0OxvXVHgURT` ($25/mo) |
| `STRIPE_PRICE_PROFESSIONAL` | Yes | `price_1ThYCX377xE4C0Oxxt8xpB26` ($60/mo, Stripe product "Pro") |
| `STRIPE_PRICE_BUSINESS` | Yes | `price_1ThjC9377xE4C0Ox7EbgD06I` ($150/mo) |

Without Stripe keys, subscribe activates in **dev mode** (no real charge).

### Webhook (production)

In Stripe Dashboard → Developers → Webhooks, add:

- **URL:** `https://YOUR_DOMAIN/api/billing/webhook`
- **Events:** `checkout.session.completed`, `invoice.paid`, `customer.subscription.updated`, `customer.subscription.deleted`
- Copy the signing secret to `STRIPE_WEBHOOK_SECRET` in Render.

Plans are chosen in-app via Account → Choose a plan (Stripe Checkout). The Stripe Pricing Table embed (`prctbl_...`) is optional and not used by the app UI.
