# Launch Checklist — First 5 Paying Customers

## Pre-launch (product)

- [ ] Run `py -m pytest tests/` — full studio flow passes
- [ ] Complete 3 internal test runs; verify `.md` and `.json` quality
- [ ] Set `ANTHROPIC_API_KEY` for richer profiles (optional)
- [ ] Configure Stripe keys and $49/mo price ID in `.env`

## Validation (weeks 1–3)

- [ ] Complete 10–15 analyst interviews using [interview-guide.md](interview-guide.md)
- [ ] Update [product-spec.md](product-spec.md) with confirmed persona
- [ ] Target: ≥30% would pay $50/mo after seeing Studio output

## Iterate to 8/10 success (weeks 6–10)

- [ ] Onboard 10 test users from interview pool
- [ ] Track funnel via `GET /api/events/funnel` per user
- [ ] Fix drop-off after tasks 1–2 (most common)
- [ ] Success: 8/10 complete Studio and download artifacts

## Billing (week 9)

- [ ] Stripe Checkout live at `/api/billing/checkout`
- [ ] Entry tier: $39–79/mo (default $49)
- [ ] Dev mode fallback when Stripe not configured

## First 5 customers (weeks 10–12)

- [ ] Network-led outreach — no paid ads
- [ ] Offer: complete Studio → subscribe to keep agent active
- [ ] Target: $200–500 MRR (5 × $49 = $245)
- [ ] Document wins/losses; decide next 90-day focus

## Metrics to watch

| Metric | Target |
|--------|--------|
| Studio completion rate | ≥80% |
| Median completion time | <35 min |
| Paying conversion (completed → paid) | ≥50% |
| MRR month 3 | $300–500 |
