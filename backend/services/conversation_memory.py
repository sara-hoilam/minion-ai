"""Conversation memory: short-term window, rolling summaries, topic recall.

Designed for SQLite today; schema maps cleanly to Supabase (Postgres + Storage + pgvector).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from backend.config import (
    MEMORY_FOLDER,
    MEMORY_SHORT_TERM_MESSAGES,
    MEMORY_SUMMARIZE_BATCH,
    MEMORY_TOPIC_RELEVANCE_TOP_K,
)
from backend.models import ChatMessage, ThreadMemoryState, ThreadTopic, db
from backend.services.cursor_llm import complete as cursor_complete
from backend.services.memory_jobs import is_compaction_running

logger = logging.getLogger(__name__)

_AMBIGUOUS_REFERENCE_PATTERNS = (
    re.compile(r"\bwhich (stock|stocks|ones?|ticker|tickers|pick|picks|recommendation|recommendations)\b", re.I),
    re.compile(r"\bwhat did you (recommend|suggest|say|list|pick)\b", re.I),
    re.compile(r"\b(you|did you) (recommend|suggested|mentioned|said|listed|named)\b", re.I),
    re.compile(r"\b(the|those|these) (stock|stocks|pick|picks|recommendation|recommendations|ones?)\b", re.I),
    re.compile(r"\bfrom (above|earlier|before)\b", re.I),
    re.compile(r"\b(that|the) (list|table|answer|response)\b", re.I),
    re.compile(r"\bwhich (one|ones) (was|were)\b", re.I),
    re.compile(r"\bremind me (what|which)\b", re.I),
    re.compile(r"\bwhat were they\b", re.I),
)


def is_ambiguous_reference(user_message: str) -> bool:
    """User refers to prior content without naming the topic (e.g. 'which stocks?')."""
    text = (user_message or "").strip()
    if not text:
        return False
    if len(text.split()) > 18:
        return False
    lower = text.lower()
    return any(pat.search(lower) for pat in _AMBIGUOUS_REFERENCE_PATTERNS)


_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "will", "would", "could", "should", "may", "might", "must", "shall", "can",
    "this", "that", "these", "those", "i", "you", "he", "she", "it", "we", "they", "my",
    "your", "what", "how", "when", "where", "why", "who", "about", "from", "into", "me",
})


@dataclass
class ConversationMemoryContext:
    short_term_history: list[dict] = field(default_factory=list)
    rolling_summary: str = ""
    relevant_topics: list[dict] = field(default_factory=list)
    topic_catalog: list[str] = field(default_factory=list)
    memory_prompt_block: str = ""


def message_eligible_for_history(msg: ChatMessage) -> bool:
    if msg.role not in ("user", "assistant"):
        return False
    meta = msg.meta or {}
    if meta.get("cancelled"):
        return False
    if meta.get("type") == "plan_proposal":
        return False
    return True


def load_thread_messages(thread_id: int) -> list[ChatMessage]:
    return (
        ChatMessage.query.filter_by(thread_id=thread_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )


def messages_to_history(messages: list[ChatMessage]) -> list[dict]:
    return [
        {"id": m.id, "role": m.role, "content": m.content}
        for m in messages
        if message_eligible_for_history(m)
    ]


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]{3,}", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS}


def _topic_recency_boost(topic: ThreadTopic, all_topics: list[ThreadTopic]) -> float:
    """Prefer newer topics when scores are otherwise close."""
    if not all_topics:
        return 0.0
    ordered = sorted(
        all_topics,
        key=lambda t: t.updated_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    try:
        rank = ordered.index(topic)
    except ValueError:
        return 0.0
    if rank == 0:
        return 0.45
    if rank == 1:
        return 0.2
    return max(0.0, 0.12 - rank * 0.03)


def _topic_relevance_score(
    user_message: str,
    topic: ThreadTopic,
    *,
    all_topics: list[ThreadTopic] | None = None,
) -> float:
    query = _tokenize(user_message)
    if not query:
        return 0.0
    corpus_parts = [topic.title or "", topic.summary or ""]
    corpus_parts.extend(topic.key_insights or [])
    corpus_parts.extend(topic.keywords or [])
    doc = _tokenize(" ".join(corpus_parts))
    if not doc:
        return 0.0
    overlap = len(query & doc)
    title_overlap = len(query & _tokenize(topic.title or ""))
    score = overlap / max(len(query), 1) + title_overlap * 0.35
    if all_topics:
        score += _topic_recency_boost(topic, all_topics)
    if topic.last_referenced_at:
        score += 0.03
    return score


def select_relevant_topics(
    user_message: str,
    topics: list[ThreadTopic],
    *,
    top_k: int | None = None,
    ambiguous_reference: bool = False,
) -> list[ThreadTopic]:
    top_k = top_k or MEMORY_TOPIC_RELEVANCE_TOP_K
    active = [t for t in topics if (t.status or "active") == "active"]
    if not active:
        return []

    if ambiguous_reference:
        # Vague follow-ups should be resolved from recent transcript, not old topic cards.
        return []

    ranked = sorted(
        active,
        key=lambda t: _topic_relevance_score(user_message, t, all_topics=active),
        reverse=True,
    )
    chosen = [
        t for t in ranked
        if _topic_relevance_score(user_message, t, all_topics=active) > 0.12
    ]
    if not chosen and ranked:
        best = _topic_relevance_score(user_message, ranked[0], all_topics=active)
        if best > 0.08:
            chosen = ranked[:1]
    return chosen[:top_k]


def _get_or_create_memory_state(thread_id: int) -> ThreadMemoryState:
    state = ThreadMemoryState.query.filter_by(thread_id=thread_id).first()
    if state:
        return state
    state = ThreadMemoryState(thread_id=thread_id, rolling_summary="", summary_through_message_id=0)
    db.session.add(state)
    db.session.flush()
    return state


def format_recent_conversation_block(recent_history: list[dict], *, max_messages: int = 8) -> str:
    lines: list[str] = []
    for item in recent_history[-max_messages:]:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {content[:2500]}")
    if not lines:
        return ""
    return (
        "RECENT CONVERSATION (primary source — resolve ambiguous follow-ups from the latest exchange here):\n"
        + "\n\n".join(lines)
    )


def format_memory_prompt_block(
    *,
    rolling_summary: str,
    relevant_topics: list[dict],
    topic_catalog: list[str],
    ambiguous_reference: bool = False,
    recent_history: list[dict] | None = None,
) -> str:
    parts: list[str] = []

    if ambiguous_reference:
        parts.append(
            "DISAMBIGUATION RULE: The user's message is a vague follow-up without naming a topic. "
            "Answer using the MOST RECENT exchange in RECENT CONVERSATION below — "
            "NOT older summarized topics unless the user explicitly names them."
        )

    recent_block = format_recent_conversation_block(recent_history or [])
    if recent_block:
        parts.append(recent_block)

    if rolling_summary.strip() and not ambiguous_reference:
        parts.append(f"LONG-TERM CONVERSATION SUMMARY (background only):\n{rolling_summary.strip()}")
    elif rolling_summary.strip() and ambiguous_reference:
        parts.append(
            "OLDER CONVERSATION SUMMARY (background only — do NOT prefer this over RECENT CONVERSATION "
            "for unnamed follow-ups):\n"
            + rolling_summary.strip()[:4000]
        )

    if relevant_topics:
        lines = []
        for t in relevant_topics:
            title = t.get("title") or "Topic"
            summary = (t.get("summary") or "").strip()
            insights = t.get("key_insights") or []
            block = f"- **{title}**"
            if summary:
                block += f": {summary}"
            if insights:
                block += "\n  Key insights: " + "; ".join(str(i) for i in insights[:5])
            lines.append(block)
        parts.append(
            "RELEVANT HISTORICAL TOPICS (background — only if the user clearly refers to them):\n"
            + "\n".join(lines)
        )

    if topic_catalog and len(topic_catalog) > len(relevant_topics) and not ambiguous_reference:
        other = [t for t in topic_catalog if t not in {x.get("title") for x in relevant_topics}]
        if other:
            parts.append("OTHER TOPICS IN THIS CHAT: " + ", ".join(other[:12]))

    if not parts:
        return ""

    return (
        "CONVERSATION MEMORY (automatic — do not mention this section to the user):\n"
        + "\n\n".join(parts)
    )


def build_memory_context(
    thread_id: int,
    user_message: str,
    *,
    mark_topics_referenced: bool = True,
) -> ConversationMemoryContext:
    messages = load_thread_messages(thread_id)
    eligible = [m for m in messages if message_eligible_for_history(m)]
    history = messages_to_history(eligible)

    state = ThreadMemoryState.query.filter_by(thread_id=thread_id).first()
    rolling_summary = (state.rolling_summary or "") if state else ""

    short_term = history[-MEMORY_SHORT_TERM_MESSAGES:] if history else []
    ambiguous = is_ambiguous_reference(user_message)

    topics = (
        ThreadTopic.query.filter_by(thread_id=thread_id, status="active")
        .order_by(ThreadTopic.updated_at.desc())
        .all()
    )
    relevant = select_relevant_topics(
        user_message,
        topics,
        ambiguous_reference=ambiguous,
    )
    topic_catalog = [t.title for t in topics if t.title]

    if mark_topics_referenced and relevant:
        now = datetime.now(timezone.utc)
        for t in relevant:
            t.last_referenced_at = now
        db.session.commit()

    relevant_dicts = [
        {
            "id": t.id,
            "title": t.title,
            "summary": t.summary,
            "key_insights": t.key_insights or [],
        }
        for t in relevant
    ]

    memory_block = format_memory_prompt_block(
        rolling_summary=rolling_summary,
        relevant_topics=relevant_dicts,
        topic_catalog=topic_catalog,
        ambiguous_reference=ambiguous,
        recent_history=short_term,
    )

    return ConversationMemoryContext(
        short_term_history=short_term,
        rolling_summary=rolling_summary,
        relevant_topics=relevant_dicts,
        topic_catalog=topic_catalog,
        memory_prompt_block=memory_block,
    )


def _memory_dir(user_id: int, thread_id: int) -> Path:
    path = MEMORY_FOLDER / str(user_id) / str(thread_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_memory_artifacts(
    user_id: int,
    thread_id: int,
    *,
    rolling_summary: str,
    topics: list[ThreadTopic],
) -> tuple[str | None, str | None]:
    base = _memory_dir(user_id, thread_id)
    summary_path = base / "conversation_summary.md"
    topics_path = base / "topics.json"

    summary_body = f"# Conversation summary (thread {thread_id})\n\n{rolling_summary.strip()}\n"
    summary_path.write_text(summary_body, encoding="utf-8")

    topics_payload = [
        {
            "id": t.id,
            "title": t.title,
            "summary": t.summary,
            "key_insights": t.key_insights or [],
            "keywords": t.keywords or [],
            "source_message_ids": t.source_message_ids or [],
            "status": t.status,
            "updated_at": (t.updated_at or datetime.now(timezone.utc)).isoformat(),
        }
        for t in topics
    ]
    topics_path.write_text(json.dumps(topics_payload, indent=2), encoding="utf-8")

    return str(summary_path), str(topics_path)


def _parse_ai_json(text: str) -> dict | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def _format_messages_for_llm(messages: list[ChatMessage]) -> str:
    lines = []
    for m in messages:
        label = "User" if m.role == "user" else "Assistant"
        content = (m.content or "").strip()[:2000]
        if content:
            lines.append(f"{label}: {content}")
    return "\n".join(lines)


def _summarize_segment(messages: list[ChatMessage], agent_name: str) -> str:
    if not messages:
        return ""
    transcript = _format_messages_for_llm(messages)
    prompt = f"""Summarize this conversation segment for long-term memory.
Preserve: decisions, numbers, deliverables, open questions, and topic boundaries.
Write 3-6 concise paragraphs. Agent name: {agent_name}.

Transcript:
{transcript[:12000]}"""
    result = cursor_complete(
        "You compress chat history into durable summaries without losing factual detail.",
        prompt,
    )
    if result:
        return result.strip()
    return _rule_summarize_segment(messages)


def _rule_summarize_segment(messages: list[ChatMessage]) -> str:
    lines = []
    for m in messages[-8:]:
        role = "User" if m.role == "user" else "Assistant"
        snippet = (m.content or "").strip()[:300]
        if snippet:
            lines.append(f"{role}: {snippet}")
    return "Earlier conversation (auto-summary):\n" + "\n".join(lines)


def _extract_topics_from_segment(
    messages: list[ChatMessage],
    agent_name: str,
) -> list[dict]:
    transcript = _format_messages_for_llm(messages)
    prompt = f"""Extract distinct conversation topics from this segment.
Return JSON only:
{{
  "topics": [
    {{
      "title": "short topic label",
      "summary": "2-3 sentence summary",
      "key_insights": ["insight 1", "insight 2"],
      "keywords": ["kw1", "kw2"]
    }}
  ]
}}

Agent: {agent_name}
Transcript:
{transcript[:10000]}"""
    raw = cursor_complete(
        "You identify conversation topics and durable insights for memory retrieval.",
        prompt,
    )
    if raw:
        parsed = _parse_ai_json(raw)
        if parsed and isinstance(parsed.get("topics"), list):
            return parsed["topics"]
    return _rule_extract_topics(messages)


def _rule_extract_topics(messages: list[ChatMessage]) -> list[dict]:
    user_msgs = [m.content for m in messages if m.role == "user" and (m.content or "").strip()]
    if not user_msgs:
        return []
    seed = user_msgs[0].strip()[:120]
    title = seed.split(".")[0].split("?")[0][:80] or "Earlier discussion"
    return [{
        "title": title,
        "summary": seed,
        "key_insights": [],
        "keywords": list(_tokenize(seed))[:8],
    }]


def _merge_topic(existing: ThreadTopic, incoming: dict, message_ids: list[int]) -> None:
    new_insights = incoming.get("key_insights") or []
    merged_insights = list(dict.fromkeys((existing.key_insights or []) + new_insights))[:12]
    existing.key_insights = merged_insights
    if incoming.get("summary"):
        if existing.summary:
            existing.summary = f"{existing.summary.strip()}\n\n{incoming['summary'].strip()}"[:4000]
        else:
            existing.summary = incoming["summary"][:4000]
    kw = list(dict.fromkeys((existing.keywords or []) + (incoming.get("keywords") or [])))[:20]
    existing.keywords = kw
    ids = list(dict.fromkeys((existing.source_message_ids or []) + message_ids))
    existing.source_message_ids = ids[-50:]
    existing.updated_at = datetime.now(timezone.utc)


def _upsert_topics(
    thread_id: int,
    agent_session_id: int | None,
    topic_payloads: list[dict],
    message_ids: list[int],
) -> list[ThreadTopic]:
    saved: list[ThreadTopic] = []
    for payload in topic_payloads:
        title = (payload.get("title") or "").strip()[:255]
        if not title:
            continue
        existing = (
            ThreadTopic.query.filter_by(thread_id=thread_id, title=title, status="active").first()
        )
        if existing:
            _merge_topic(existing, payload, message_ids)
            saved.append(existing)
        else:
            topic = ThreadTopic(
                thread_id=thread_id,
                agent_session_id=agent_session_id,
                title=title,
                summary=(payload.get("summary") or "")[:4000],
                key_insights=(payload.get("key_insights") or [])[:12],
                keywords=(payload.get("keywords") or [])[:20],
                source_message_ids=message_ids[-50:],
                status="active",
            )
            db.session.add(topic)
            saved.append(topic)
    db.session.flush()
    return saved


def get_thread_memory_snapshot(thread_id: int) -> dict:
    """Serializable memory view for API / UI."""
    state = ThreadMemoryState.query.filter_by(thread_id=thread_id).first()
    topics = (
        ThreadTopic.query.filter_by(thread_id=thread_id, status="active")
        .order_by(ThreadTopic.updated_at.desc())
        .all()
    )
    eligible_count = len([
        m for m in load_thread_messages(thread_id)
        if message_eligible_for_history(m)
    ])
    return {
        "rolling_summary": (state.rolling_summary or "") if state else "",
        "summary_through_message_id": (state.summary_through_message_id or 0) if state else 0,
        "last_compacted_at": state.last_compacted_at.isoformat() if state and state.last_compacted_at else None,
        "compaction_status": (state.compaction_status or "idle") if state else "idle",
        "compaction_running": is_compaction_running(thread_id),
        "eligible_message_count": eligible_count,
        "topics": [
            {
                "id": t.id,
                "title": t.title,
                "summary": t.summary,
                "key_insights": t.key_insights or [],
                "last_referenced_at": t.last_referenced_at.isoformat() if t.last_referenced_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in topics
        ],
    }


def maybe_compact_thread(
    thread_id: int,
    user_id: int,
    agent_name: str,
    *,
    agent_session_id: int | None = None,
) -> bool:
    """
    When history exceeds short-term window, summarize older messages and extract topics.
    Returns True if compaction ran.
    """
    state = _get_or_create_memory_state(thread_id)
    if state.compaction_status == "running":
        return False

    messages = load_thread_messages(thread_id)
    eligible = [m for m in messages if message_eligible_for_history(m)]
    if len(eligible) <= MEMORY_SHORT_TERM_MESSAGES:
        return False

    through_id = state.summary_through_message_id or 0

    compactable = [m for m in eligible if m.id > through_id]
    reserve = MEMORY_SHORT_TERM_MESSAGES
    if len(compactable) <= reserve:
        return False

    to_summarize = compactable[: -reserve]
    if len(to_summarize) < MEMORY_SUMMARIZE_BATCH:
        return False

    state.compaction_status = "running"
    db.session.commit()

    try:
        segment_summary = _summarize_segment(to_summarize, agent_name)
        if not segment_summary:
            state.compaction_status = "idle"
            db.session.commit()
            return False

        if state.rolling_summary:
            state.rolling_summary = f"{state.rolling_summary.strip()}\n\n---\n\n{segment_summary}"[:16000]
        else:
            state.rolling_summary = segment_summary[:16000]

        state.summary_through_message_id = to_summarize[-1].id
        state.last_compacted_at = datetime.now(timezone.utc)
        state.updated_at = datetime.now(timezone.utc)

        message_ids = [m.id for m in to_summarize]
        topic_payloads = _extract_topics_from_segment(to_summarize, agent_name)
        _upsert_topics(thread_id, agent_session_id, topic_payloads, message_ids)

        all_topics = (
            ThreadTopic.query.filter_by(thread_id=thread_id, status="active")
            .order_by(ThreadTopic.updated_at.desc())
            .all()
        )
        summary_path, topics_path = _write_memory_artifacts(
            user_id,
            thread_id,
            rolling_summary=state.rolling_summary,
            topics=all_topics,
        )
        state.summary_file_path = summary_path
        state.topics_file_path = topics_path
        state.compaction_status = "idle"
        db.session.commit()
        logger.info("Compacted thread %s through message %s", thread_id, state.summary_through_message_id)
        return True
    except Exception:
        state.compaction_status = "failed"
        db.session.commit()
        raise
