"""Cursor Cloud Agents API — Composer 2.5 for chat and app LLM calls."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

from backend.config import CURSOR_API_BASE, CURSOR_API_KEY, CURSOR_MODEL, MEMORY_SHORT_TERM_MESSAGES

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = frozenset({"FINISHED", "ERROR", "CANCELLED", "EXPIRED"})
DEFAULT_POLL_INTERVAL_S = 2.0
FAST_POLL_INTERVAL_S = 0.35
DEFAULT_MAX_WAIT_S = 180
POLL_REQUEST_TIMEOUT_S = 8


def is_configured() -> bool:
    return bool(CURSOR_API_KEY)


def _request(method: str, path: str, body: dict | None = None, timeout: int = 60) -> dict:
    if not CURSOR_API_KEY:
        raise RuntimeError("Cursor API key is not configured")

    url = f"{CURSOR_API_BASE.rstrip('/')}{path}"
    data = None
    headers = {
        "Authorization": f"Bearer {CURSOR_API_KEY}",
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Cursor API {method} {path} failed ({exc.code}): {detail}") from exc


def _model_payload() -> dict:
    return {
        "id": CURSOR_MODEL,
        "params": [{"id": "fast", "value": "true"}],
    }


def cancel_run(agent_id: str, run_id: str) -> None:
    """Cancel an active Cursor cloud agent run."""
    if not is_configured():
        return
    try:
        _request("POST", f"/v1/agents/{agent_id}/runs/{run_id}/cancel", timeout=10)
    except RuntimeError as exc:
        if "409" not in str(exc):
            raise


def _poll_run(
    agent_id: str,
    run_id: str,
    max_wait_s: int = DEFAULT_MAX_WAIT_S,
    *,
    cancel_check=None,
    on_tick=None,
    on_run_start=None,
) -> str | None:
    if on_run_start:
        on_run_start(agent_id, run_id)

    deadline = time.time() + max_wait_s
    started = time.time()
    poll_interval = FAST_POLL_INTERVAL_S if cancel_check else DEFAULT_POLL_INTERVAL_S
    while time.time() < deadline:
        if cancel_check and cancel_check():
            logger.info("Cursor run %s cancelled by user", run_id)
            try:
                cancel_run(agent_id, run_id)
            except Exception as exc:
                logger.warning("Cursor cancel_run failed: %s", exc)
            return None
        data = _request(
            "GET",
            f"/v1/agents/{agent_id}/runs/{run_id}",
            timeout=POLL_REQUEST_TIMEOUT_S,
        )
        status = data.get("status")
        if on_tick:
            on_tick(status, time.time() - started)
        if status in TERMINAL_STATUSES:
            if status == "FINISHED":
                return (data.get("result") or "").strip() or None
            logger.warning("Cursor run %s ended with status %s", run_id, status)
            return None
        time.sleep(poll_interval)
    logger.warning("Cursor run %s timed out after %ss", run_id, max_wait_s)
    return None


def _format_history(history: list[dict]) -> str:
    lines = []
    for item in history[-MEMORY_SHORT_TERM_MESSAGES:]:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {content}")
    return "\n".join(lines)


def _build_prompt(system: str, user: str, history: list[dict] | None = None) -> str:
    parts = []
    if system.strip():
        parts.append(f"SYSTEM INSTRUCTIONS:\n{system.strip()}")
    if history:
        hist = _format_history(history)
        if hist:
            parts.append(f"CONVERSATION HISTORY:\n{hist}")
    parts.append(f"CURRENT REQUEST:\n{user.strip()}")
    parts.append(
        "Reply directly to the current request. Follow system instructions. "
        "Do not mention tools, agents, or internal steps unless asked."
    )
    return "\n\n".join(parts)


def create_cloud_agent(prompt_text: str, name: str | None = None) -> tuple[str, str]:
    """Create a no-repo cloud agent and return (agent_id, run_id)."""
    body: dict = {
        "prompt": {"text": prompt_text},
        "model": _model_payload(),
    }
    if name:
        body["name"] = name[:100]
    data = _request("POST", "/v1/agents", body)
    agent_id = data["agent"]["id"]
    run_id = data["run"]["id"]
    return agent_id, run_id


def send_follow_up(cloud_agent_id: str, prompt_text: str) -> str:
    """Send a follow-up run on an existing cloud agent. Returns run_id."""
    data = _request(
        "POST",
        f"/v1/agents/{cloud_agent_id}/runs",
        {"prompt": {"text": prompt_text}},
    )
    return data["run"]["id"]


def complete(
    system: str,
    user: str,
    *,
    history: list[dict] | None = None,
    max_wait_s: int = DEFAULT_MAX_WAIT_S,
    cancel_check=None,
    on_tick=None,
    on_run_start=None,
) -> str | None:
    """One-shot completion using an ephemeral no-repo cloud agent."""
    if not is_configured():
        return None
    try:
        prompt = _build_prompt(system, user, history)
        agent_id, run_id = create_cloud_agent(prompt)
        return _poll_run(
            agent_id,
            run_id,
            max_wait_s=max_wait_s,
            cancel_check=cancel_check,
            on_tick=on_tick,
            on_run_start=on_run_start,
        )
    except Exception as exc:
        logger.exception("Cursor complete failed: %s", exc)
        return None


def chat(
    system: str,
    user_message: str,
    *,
    history: list[dict] | None = None,
    cloud_agent_id: str | None = None,
    agent_name: str | None = None,
    file_context: str = "",
    max_wait_s: int = DEFAULT_MAX_WAIT_S,
    cancel_check=None,
    on_tick=None,
    on_run_start=None,
) -> tuple[str | None, str | None]:
    """
    Multi-turn aware chat via Cursor Cloud Agents.
    Returns (assistant_text, cloud_agent_id).
    """
    if not is_configured():
        return None, cloud_agent_id

    user = user_message
    if file_context.strip():
        user = f"{user_message}\n\nAttached context:\n{file_context[:8000]}"

    try:
        if cloud_agent_id:
            run_id = send_follow_up(cloud_agent_id, user)
            text = _poll_run(
                cloud_agent_id,
                run_id,
                max_wait_s=max_wait_s,
                cancel_check=cancel_check,
                on_tick=on_tick,
                on_run_start=on_run_start,
            )
            return text, cloud_agent_id

        prompt = _build_prompt(system, user, history)
        agent_id, run_id = create_cloud_agent(prompt, name=agent_name)
        text = _poll_run(
            agent_id,
            run_id,
            max_wait_s=max_wait_s,
            cancel_check=cancel_check,
            on_tick=on_tick,
            on_run_start=on_run_start,
        )
        return text, agent_id
    except Exception as exc:
        logger.exception("Cursor chat failed: %s", exc)
        return None, cloud_agent_id
