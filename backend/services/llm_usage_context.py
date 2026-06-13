"""Request-scoped attribution for LLM runs (user, thread, source)."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class LlmUsageContext:
    user_id: int
    thread_id: int | None = None
    session_id: int | None = None
    source: str = "chat"


_ctx: ContextVar[LlmUsageContext | None] = ContextVar("llm_usage_ctx", default=None)


def get_llm_usage_context() -> LlmUsageContext | None:
    return _ctx.get()


@contextmanager
def llm_usage_scope(ctx: LlmUsageContext):
    token = _ctx.set(ctx)
    try:
        yield
    finally:
        _ctx.reset(token)
