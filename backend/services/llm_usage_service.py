"""Fetch Cursor run usage and persist per-user LLM cost events."""

from __future__ import annotations

import logging
import time
from typing import Any

from flask import has_app_context

from backend.config import CURSOR_MODEL
from backend.models import LlmUsageEvent, UserSubscription, db
from backend.services.billing_plans import TOKEN_ALLOWANCE_RATIO, actual_cost_to_billed_usd
from backend.services.llm_usage_context import get_llm_usage_context
from backend.services.subscription_service import _now

logger = logging.getLogger(__name__)

# Composer 2.5 Fast (default when fast=true) — USD per million tokens.
_INPUT_USD_PER_M = 3.0
_OUTPUT_USD_PER_M = 15.0
_CACHE_READ_USD_PER_M = 0.60
_CACHE_WRITE_USD_PER_M = 3.0

_USAGE_FETCH_ATTEMPTS = 4
_USAGE_FETCH_DELAY_S = 0.75


def _resolve_user_id() -> int | None:
    ctx = get_llm_usage_context()
    if ctx and ctx.user_id:
        return ctx.user_id
    if not has_app_context():
        return None
    try:
        from flask_login import current_user

        if current_user and getattr(current_user, "is_authenticated", False):
            return int(current_user.id)
    except Exception:
        pass
    return None


def tokens_to_cost_usd(usage: dict[str, Any]) -> float:
    """Actual Cursor API cost for a run (before Minion margin)."""
    inp = int(usage.get("inputTokens") or 0)
    out = int(usage.get("outputTokens") or 0)
    cache_read = int(usage.get("cacheReadTokens") or 0)
    cache_write = int(usage.get("cacheWriteTokens") or 0)
    cost = (
        inp * _INPUT_USD_PER_M
        + out * _OUTPUT_USD_PER_M
        + cache_read * _CACHE_READ_USD_PER_M
        + cache_write * _CACHE_WRITE_USD_PER_M
    ) / 1_000_000
    return round(max(cost, 0.0), 6)


def fetch_run_usage(agent_id: str, run_id: str) -> dict[str, Any] | None:
    from backend.services.cursor_llm import fetch_agent_run_usage

    for attempt in range(_USAGE_FETCH_ATTEMPTS):
        try:
            usage = fetch_agent_run_usage(agent_id, run_id)
            if usage and int(usage.get("totalTokens") or 0) > 0:
                return usage
        except Exception as exc:
            logger.warning("Usage fetch attempt %s for run %s failed: %s", attempt + 1, run_id, exc)
        if attempt + 1 < _USAGE_FETCH_ATTEMPTS:
            time.sleep(_USAGE_FETCH_DELAY_S)
    return None


def monthly_billed_usage_usd(user_id: int, *, period_start=None, period_end=None) -> float:
    q = db.session.query(db.func.coalesce(db.func.sum(LlmUsageEvent.billed_usd), 0)).filter(
        LlmUsageEvent.user_id == user_id,
    )
    if period_start is not None:
        q = q.filter(LlmUsageEvent.created_at >= period_start)
    if period_end is not None:
        q = q.filter(LlmUsageEvent.created_at < period_end)
    return float(q.scalar() or 0)


def record_cursor_run(
    agent_id: str,
    run_id: str,
    *,
    run_status: str = "FINISHED",
    model: str | None = None,
) -> LlmUsageEvent | None:
    if run_status != "FINISHED":
        return None
    if not has_app_context():
        logger.debug("Skipping llm usage log outside app context (run %s)", run_id)
        return None

    user_id = _resolve_user_id()
    if not user_id:
        logger.debug("Skipping llm usage log: no user (run %s)", run_id)
        return None

    existing = LlmUsageEvent.query.filter_by(cursor_run_id=run_id).first()
    if existing:
        return existing

    usage = fetch_run_usage(agent_id, run_id)
    if not usage:
        logger.info("No Cursor usage recorded yet for run %s", run_id)
        return None

    ctx = get_llm_usage_context()
    actual_cost = tokens_to_cost_usd(usage)
    billed = actual_cost_to_billed_usd(actual_cost)
    total = int(usage.get("totalTokens") or 0)

    event = LlmUsageEvent(
        user_id=user_id,
        thread_id=ctx.thread_id if ctx else None,
        session_id=ctx.session_id if ctx else None,
        cursor_agent_id=agent_id,
        cursor_run_id=run_id,
        model=model or CURSOR_MODEL,
        source=ctx.source if ctx else "unknown",
        run_status=run_status,
        input_tokens=int(usage.get("inputTokens") or 0),
        output_tokens=int(usage.get("outputTokens") or 0),
        cache_read_tokens=int(usage.get("cacheReadTokens") or 0),
        cache_write_tokens=int(usage.get("cacheWriteTokens") or 0),
        total_tokens=total,
        cost_usd=actual_cost,
        billed_usd=billed,
    )
    db.session.add(event)

    if billed > 0:
        sub = UserSubscription.query.filter_by(user_id=user_id).first()
        if sub:
            sub.token_used_usd = float(sub.token_used_usd or 0) + billed
            sub.updated_at = _now()

    db.session.commit()
    logger.info(
        "Logged LLM usage user=%s run=%s tokens=%s actual_usd=%s billed_usd=%s (margin %.0f%%)",
        user_id,
        run_id,
        total,
        actual_cost,
        billed,
        (1 - TOKEN_ALLOWANCE_RATIO) * 100,
    )
    return event


def sync_subscription_usage_from_events(user) -> UserSubscription | None:
    """Reconcile subscription token_used_usd from logged billed amounts in the billing period."""
    sub = UserSubscription.query.filter_by(user_id=user.id).first()
    if not sub:
        return None
    total = monthly_billed_usage_usd(
        user.id,
        period_start=sub.current_period_start,
        period_end=sub.current_period_end,
    )
    sub.token_used_usd = round(total, 6)
    sub.updated_at = _now()
    db.session.commit()
    return sub
