"""Live generation progress for chat threads (thinking + delegation)."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from backend.models import ChatThread, db


def _preview_message(message: str, max_len: int = 160) -> str:
    text = message.strip()
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


def _looks_date_question(lower: str) -> bool:
    return bool(
        re.search(r"\bwhat(?:'s| is) the (date|time|day)\b", lower)
        or re.search(r"\bwhat (date|time|day)\b", lower)
        or "today's date" in lower
        or "current date" in lower
    )


def _looks_definition(lower: str) -> bool:
    return bool(re.search(r"\bwhat does .+ mean\b", lower) or re.search(r"\bdefine\b", lower))


def _looks_greeting(lower: str) -> bool:
    normalized = re.sub(r"[^\w\s]", "", lower).strip()
    return normalized in {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay"}


def build_simple_thought_chain(
    user_message: str,
    agent_name: str,
    *,
    routing: str = "simple",
    skill: str | None = None,
) -> list[str]:
    """Human-readable reasoning steps shown while the agent composes a reply."""
    preview = _preview_message(user_message)
    lower = user_message.lower()
    chain = [f"Reading your message: «{preview}»"]

    if routing == "specialist" and skill:
        chain.append(f"This calls for {skill} — I'll apply that lens directly.")
        chain.append("Pulling relevant context from this thread and any attachments.")
    elif routing == "direct" or _looks_greeting(lower) or _looks_date_question(lower) or _looks_definition(lower):
        chain.append("I can answer this directly — no specialist delegation needed.")
        if _looks_date_question(lower):
            chain.append("Checking the current date and timezone.")
        elif _looks_definition(lower):
            chain.append("Recalling the concept and how to explain it clearly.")
        elif _looks_greeting(lower):
            chain.append("Preparing a brief, friendly reply.")
        else:
            chain.append("Using general knowledge plus anything useful from earlier in the chat.")
    else:
        chain.append(f"{agent_name} is choosing the leanest way to help.")
        chain.append("Scanning conversation history for useful context.")

    chain.append("Drafting a clear answer in my voice.")
    chain.append("Reviewing tone and completeness before sending.")
    return chain


def build_planning_thought_chain(
    user_message: str,
    agent_name: str,
    skill_agents: list[dict],
    *,
    matched_skills: list[dict] | None = None,
) -> list[str]:
    """Thought steps shown while the manager evaluates the team roster."""
    preview = _preview_message(user_message)
    roster = [a.get("skill") or "Specialist" for a in skill_agents]
    roster_label = ", ".join(roster[:6]) + ("…" if len(roster) > 6 else "")

    chain = [
        f"Reading your message: «{preview}»",
        f"{agent_name} (manager) is reviewing the request.",
        f"Available specialists ({len(roster)}): {roster_label}",
        "Scoring each skill against what you're asking for…",
    ]

    # Do not guess which specialists are in/out before the manager plan is ready —
    # keyword heuristics often disagree with the final delegation plan.
    chain.append("Manager is evaluating which specialists are needed…")
    chain.append("Deciding assignments and execution order…")
    return chain


def _strip_premature_skill_guesses(chain: list[str]) -> list[str]:
    """Remove heuristic skip/relevance lines that may contradict the final plan."""
    out: list[str] = []
    for line in chain:
        if "looks relevant — likely needed" in line:
            continue
        if line.startswith("✗ Skipping ") or line.startswith("Skipping "):
            continue
        if "This spans multiple skills — I'll pick" in line:
            continue
        if "keyword scan suggests" in line.lower():
            continue
        if "manager will confirm" in line.lower():
            continue
        out.append(line)
    return out


def finalize_planning_thought_chain(
    planning_chain: list[str],
    subtasks: list[dict],
    skill_agents: list[dict],
) -> list[str]:
    """Build the authoritative thought chain once the manager plan exists."""
    prefix = _strip_premature_skill_guesses(planning_chain)
    while prefix and prefix[-1].startswith("Deciding assignments"):
        prefix.pop()
    return prefix + build_delegation_decision_thoughts(subtasks, skill_agents)


def build_subagent_thought_chain(skill: str, assignment: str) -> list[str]:
    """Thought steps shown while a specialist subagent works on a scoped task."""
    preview = _preview_message(assignment or skill, max_len=100)
    return [
        f"{skill} specialist taking the assignment",
        f"Scoped task: {preview}",
        f"Applying {skill} expertise to the deliverable",
        "Drafting focused output for the manager",
        "Checking scope and quality before handoff",
    ]


def build_synthesis_thought_chain() -> list[str]:
    return [
        "Manager reviewing specialist outputs",
        "Merging findings into one cohesive answer",
        "Trimming overlap and aligning tone",
        "Final polish before sending",
    ]


def build_delegation_decision_thoughts(
    subtasks: list[dict],
    skill_agents: list[dict],
) -> list[str]:
    """Concrete delegation decisions after the manager plan is ready."""
    selected = {(st.get("skill") or "").lower() for st in subtasks}
    thoughts = ["Delegation decisions:"]

    for i, st in enumerate(subtasks, 1):
        skill = st.get("skill") or "Specialist"
        task = (st.get("task") or skill)[:110]
        thoughts.append(f"Step {i} → {skill}: {task}")

    skipped = [
        a.get("skill") or "Specialist"
        for a in skill_agents
        if (a.get("skill") or "").lower() not in selected
    ]
    if skipped:
        label = ", ".join(skipped[:5])
        if len(skipped) > 5:
            label += f", +{len(skipped) - 5} more"
        thoughts.append(f"Not delegating to {label} — outside scope for this request.")

    return thoughts


def thought_meta_from_progress(progress: dict | None) -> dict | None:
    """Build persisted thought metadata for a completed assistant message."""
    if not progress:
        return None

    # Prefer live `thoughts` — it is reconciled when the manager plan is finalized.
    chain = list(progress.get("thoughts") or progress.get("thought_chain") or [])
    manager_plan = (progress.get("manager_plan") or "").strip()
    if manager_plan and manager_plan not in chain:
        chain.insert(0, manager_plan)

    steps = progress.get("steps") or []
    if not chain and not steps:
        return None

    duration_sec = 1
    started = progress.get("started_at")
    if started:
        try:
            start = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
            duration_sec = max(1, int((datetime.now(timezone.utc) - start).total_seconds()))
        except (TypeError, ValueError):
            duration_sec = max(1, len(chain) or 1)
    else:
        duration_sec = max(1, len(chain) or 1)

    return {
        "thoughts": chain,
        "duration_sec": duration_sec,
        "steps": steps,
        "manager_plan": manager_plan or None,
    }


def _thought_reveal_count(run_status: str | None, elapsed_s: float, chain_len: int) -> int:
    if chain_len <= 0:
        return 0
    status = (run_status or "RUNNING").upper()
    if status == "FINISHED":
        return chain_len
    if status in {"CREATING", "PENDING", "QUEUED", "STARTING"}:
        return min(1, chain_len)
    if elapsed_s < 2:
        return min(2, chain_len)
    if elapsed_s < 5:
        return min(3, chain_len)
    if elapsed_s < 10:
        return min(max(chain_len - 1, 3), chain_len)
    return chain_len


class ChatGenerationCancelled(Exception):
    """Raised when the user stops an in-flight generation."""


class ChatProgressReporter:
    """Persists incremental progress on ChatThread for frontend polling."""

    def __init__(self, thread_id: int, generation_seq: int | None = None):
        self.thread_id = thread_id
        self.generation_seq = generation_seq

    def _load_thread(self) -> ChatThread | None:
        return db.session.get(ChatThread, self.thread_id)

    def _is_stale(self, thread: ChatThread | None) -> bool:
        if not thread:
            return True
        if self.generation_seq is not None and thread.generation_seq != self.generation_seq:
            return True
        return False

    def _save(self, data: dict) -> None:
        thread = self._load_thread()
        if not thread or self._is_stale(thread):
            return
        thread.generation_progress = data
        db.session.commit()

    def snapshot(self) -> dict:
        thread = self._load_thread()
        return dict(thread.generation_progress or {}) if thread else {}

    def is_cancelled(self) -> bool:
        thread = self._load_thread()
        if self._is_stale(thread):
            return True
        return bool(thread and (thread.cancel_requested or not thread.is_generating))

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise ChatGenerationCancelled()

    def clear(self) -> None:
        thread = self._load_thread()
        if not thread or self._is_stale(thread):
            return
        thread.generation_progress = None
        thread.cancel_requested = False
        thread.active_cursor_run = None
        db.session.commit()

    def set_active_run(self, agent_id: str, run_id: str) -> None:
        thread = self._load_thread()
        if not thread or self._is_stale(thread):
            return
        thread.active_cursor_run = {"agent_id": agent_id, "run_id": run_id}
        db.session.commit()

    def begin_starting(self, agent_name: str) -> None:
        self._save({
            "mode": "starting",
            "phase": "starting",
            "phase_label": "Starting…",
            "agent_name": agent_name,
            "manager_plan": None,
            "thoughts": [f"Connecting to {agent_name}…"],
            "steps": [],
            "total_steps": 0,
            "completed_steps": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
        })

    def begin_simple(
        self,
        agent_name: str,
        user_message: str,
        *,
        routing: str = "simple",
        skill: str | None = None,
    ) -> None:
        prev = self.snapshot()
        started_at = prev.get("started_at") or datetime.now(timezone.utc).isoformat()
        chain = build_simple_thought_chain(
            user_message, agent_name, routing=routing, skill=skill
        )
        self._save({
            "started_at": started_at,
            "mode": "simple",
            "phase": "thinking",
            "phase_label": chain[0],
            "agent_name": agent_name,
            "manager_plan": None,
            "thought_chain": chain,
            "thoughts": chain[:1],
            "steps": [{
                "id": "think",
                "type": "think",
                "label": "Reasoning",
                "skill": None,
                "status": "active",
                "detail": chain[1] if len(chain) > 1 else "Working through your request.",
            }],
            "total_steps": 1,
            "completed_steps": 0,
        })

    def update_simple_thinking(self, run_status: str | None, elapsed_s: float) -> None:
        """Called from cursor_llm._poll_run as on_tick(status, elapsed_s)."""
        if self.is_cancelled():
            return
        data = self.snapshot()
        if data.get("mode") != "simple":
            return

        chain = list(data.get("thought_chain") or data.get("thoughts") or [])
        if not chain:
            return

        reveal = _thought_reveal_count(run_status, elapsed_s, len(chain))
        reveal = max(reveal, len(data.get("thoughts") or []))
        data["thoughts"] = chain[:reveal]
        data["phase_label"] = chain[min(reveal - 1, len(chain) - 1)]
        self._save(data)

    def begin_planning(
        self,
        agent_name: str,
        user_message: str,
        skill_agents: list[dict],
        *,
        matched_skills: list[dict] | None = None,
    ) -> None:
        prev = self.snapshot()
        started_at = prev.get("started_at") or datetime.now(timezone.utc).isoformat()
        chain = build_planning_thought_chain(
            user_message, agent_name, skill_agents, matched_skills=matched_skills
        )
        self._save({
            "started_at": started_at,
            "mode": "team_task",
            "phase": "planning",
            "phase_label": chain[1] if len(chain) > 1 else "Manager is planning specialist workflow…",
            "agent_name": agent_name,
            "manager_plan": None,
            "thought_chain": chain,
            "thoughts": chain[:3],
            "skill_roster": [a.get("skill") for a in skill_agents],
            "steps": [{
                "id": "plan",
                "type": "plan",
                "label": "Plan workflow",
                "skill": "Manager",
                "status": "active",
                "detail": "Evaluating which specialists to involve and what each should do.",
            }],
            "total_steps": 1,
            "completed_steps": 0,
        })

    def update_planning_thinking(self, run_status: str | None, elapsed_s: float) -> None:
        """Progressive reveal while the manager composes a delegation plan."""
        if self.is_cancelled():
            return
        data = self.snapshot()
        if data.get("mode") != "team_task" or data.get("phase") != "planning":
            return

        chain = list(data.get("thought_chain") or data.get("thoughts") or [])
        if not chain:
            return

        reveal = _thought_reveal_count(run_status, elapsed_s, len(chain))
        reveal = max(reveal, len(data.get("thoughts") or []))
        data["thoughts"] = chain[:reveal]
        data["phase_label"] = chain[min(reveal - 1, len(chain) - 1)]
        self._save(data)

    def set_manager_plan(
        self,
        reasoning: str,
        subtasks: list[dict],
        skill_agents: list[dict] | None = None,
    ) -> None:
        steps = [{
            "id": "plan",
            "type": "plan",
            "label": "Plan workflow",
            "skill": "Manager",
            "status": "done",
            "detail": reasoning,
        }]
        for i, st in enumerate(subtasks):
            skill = st.get("skill") or "Specialist"
            task = (st.get("task") or skill)[:500]
            steps.append({
                "id": f"delegate-{i}",
                "type": "delegate",
                "label": f"Delegate to {skill}",
                "skill": skill,
                "status": "queued",
                "detail": task,
            })
        steps.append({
            "id": "synthesize",
            "type": "synthesize",
            "label": "Synthesize reply",
            "skill": "Manager",
            "status": "queued",
            "detail": "Combine specialist outputs into one response.",
        })
        data = self.snapshot()
        roster = skill_agents or []
        if not roster and data.get("skill_roster"):
            roster = [{"skill": name} for name in data["skill_roster"]]

        planning_chain = list(data.get("thought_chain") or data.get("thoughts") or [])
        thoughts = finalize_planning_thought_chain(planning_chain, subtasks, roster)

        self._save({
            **data,
            "phase": "delegating",
            "phase_label": f"Delegating to {len(subtasks)} specialist{'s' if len(subtasks) != 1 else ''}…",
            "manager_plan": reasoning,
            "thought_chain": thoughts,
            "thoughts": thoughts,
            "planning_thoughts_frozen": thoughts,
            "steps": steps,
            "total_steps": len(steps),
            "completed_steps": 1,
        })

    def _begin_subagent_thoughts(self, skill: str, assignment: str) -> None:
        data = self.snapshot()
        if not data.get("planning_thoughts_frozen"):
            data["planning_thoughts_frozen"] = list(data.get("thoughts") or data.get("thought_chain") or [])
        data["active_skill"] = skill
        data["subagent_thought_chain"] = build_subagent_thought_chain(skill, assignment)
        self._save(data)

    def update_delegation_thinking(self, run_status: str | None, elapsed_s: float) -> None:
        """Progressive reveal while a specialist or synthesis run is in flight."""
        if self.is_cancelled():
            return
        data = self.snapshot()
        phase = data.get("phase")
        if phase not in ("delegating", "synthesizing"):
            return

        base = list(data.get("planning_thoughts_frozen") or data.get("thoughts") or [])
        sub_chain = list(data.get("subagent_thought_chain") or [])
        if not sub_chain:
            return

        reveal = _thought_reveal_count(run_status, elapsed_s, len(sub_chain))
        sub_revealed = sub_chain[:reveal]
        skill = data.get("active_skill") or "Specialist"
        prefix = f"── {skill} ──"
        combined = base + ([prefix] if prefix not in base else []) + sub_revealed
        data["thoughts"] = combined
        data["thought_chain"] = combined
        if sub_revealed:
            data["phase_label"] = sub_revealed[-1]
        self._save(data)

    def step_active(self, index: int, subtask: dict) -> None:
        data = self.snapshot()
        steps = list(data.get("steps") or [])
        delegate_idx = index + 1
        if delegate_idx < len(steps):
            skill = subtask.get("skill") or steps[delegate_idx].get("skill")
            steps[delegate_idx]["status"] = "active"
            steps[delegate_idx]["detail"] = (subtask.get("task") or steps[delegate_idx].get("detail", ""))[:500]
            data["steps"] = steps
            data["phase"] = "delegating"
            data["phase_label"] = f"{skill} specialist is working…"
            task_note = (subtask.get("task") or steps[delegate_idx].get("detail", ""))[:500]
            self._begin_subagent_thoughts(skill, task_note)
            data = self.snapshot()
            data["steps"] = steps
            data["phase"] = "delegating"
            data["phase_label"] = f"{skill} specialist is working…"
            data["completed_steps"] = sum(1 for s in steps if s.get("status") == "done")
            self._save(data)

    def step_done(self, index: int) -> None:
        data = self.snapshot()
        steps = list(data.get("steps") or [])
        delegate_idx = index + 1
        if delegate_idx < len(steps):
            steps[delegate_idx]["status"] = "done"
            data["steps"] = steps
            data["completed_steps"] = sum(1 for s in steps if s.get("status") == "done")
            # Keep specialist thought lines in the chain for the next delegate step.
            data["planning_thoughts_frozen"] = list(data.get("thoughts") or data.get("thought_chain") or [])
            data["subagent_thought_chain"] = []
            self._save(data)

    def begin_synthesizing(self) -> None:
        data = self.snapshot()
        steps = list(data.get("steps") or [])
        for step in steps:
            if step.get("id") == "synthesize":
                step["status"] = "active"
        data["steps"] = steps
        data["phase"] = "synthesizing"
        data["phase_label"] = "Synthesizing final response…"
        data["active_skill"] = "Manager"
        data["subagent_thought_chain"] = build_synthesis_thought_chain()
        if not data.get("planning_thoughts_frozen"):
            data["planning_thoughts_frozen"] = list(data.get("thoughts") or data.get("thought_chain") or [])
        self._save(data)

    def mark_cancelling(self) -> None:
        data = self.snapshot()
        data["phase"] = "cancelling"
        data["phase_label"] = "Stopping…"
        self._save(data)
