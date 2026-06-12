"""Conversation memory — topics, summarization hooks, retrieval."""

from backend.app import create_app
from backend.models import ChatMessage, ChatThread, ThreadTopic, User, db
from backend.services.agent_instructions import build_agent_instruction_block
from backend.services.conversation_memory import (
    build_memory_context,
    format_memory_prompt_block,
    is_ambiguous_reference,
    message_eligible_for_history,
    select_relevant_topics,
)


def _app():
    return create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DISABLE_AUTH": True,
    })


def test_agent_instruction_block_includes_working_instructions():
    block = build_agent_instruction_block({
        "full_name": "Sara",
        "current_job": "Analyst",
        "working_instructions": "Always cite data sources.",
    })
    assert "AGENT SETTINGS" in block
    assert "Always cite data sources" in block


def test_topic_relevance_selects_matching_topic():
    app = _app()
    with app.app_context():
        db.create_all()
        user = User(email="mem@test.com")
        user.set_password("password12")
        db.session.add(user)
        db.session.flush()
        thread = ChatThread(user_id=user.id, thread_type="agent_dm")
        db.session.add(thread)
        db.session.flush()
        topic = ThreadTopic(
            thread_id=thread.id,
            title="Migration funnel analysis",
            summary="Analyzed signup-to-paid conversion for Q3 migration cohort.",
            key_insights=["Drop-off at step 3", "Mobile users convert lower"],
            keywords=["funnel", "migration", "conversion"],
            status="active",
        )
        db.session.add(topic)
        db.session.commit()

        chosen = select_relevant_topics(
            "Can we revisit the migration funnel conversion findings?",
            [topic],
        )
        assert len(chosen) == 1
        assert chosen[0].title == "Migration funnel analysis"


def test_build_memory_context_includes_summary_and_short_term():
    app = _app()
    with app.app_context():
        db.create_all()
        user = User(email="mem2@test.com")
        user.set_password("password12")
        db.session.add(user)
        db.session.flush()
        thread = ChatThread(user_id=user.id, thread_type="agent_dm")
        db.session.add(thread)
        db.session.flush()

        for i in range(5):
            db.session.add(ChatMessage(
                thread_id=thread.id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"Message {i} about revenue forecasting",
            ))
        db.session.add(ThreadTopic(
            thread_id=thread.id,
            title="Revenue forecast",
            summary="Built a Q4 revenue forecast model.",
            key_insights=["Upside in enterprise"],
            keywords=["revenue", "forecast"],
            status="active",
        ))
        db.session.commit()

        ctx = build_memory_context(thread.id, "Update the revenue forecast assumptions")
        assert len(ctx.short_term_history) == 5
        assert any(t["title"] == "Revenue forecast" for t in ctx.relevant_topics)
        assert "RELEVANT HISTORICAL TOPICS" in ctx.memory_prompt_block


def test_plan_proposal_messages_excluded_from_history():
    app = _app()
    with app.app_context():
        db.create_all()
        user = User(email="mem3@test.com")
        user.set_password("password12")
        db.session.add(user)
        db.session.flush()
        thread = ChatThread(user_id=user.id)
        db.session.add(thread)
        db.session.flush()
        msg = ChatMessage(
            thread_id=thread.id,
            role="assistant",
            content="Approve my plan?",
            meta={"type": "plan_proposal"},
        )
        assert not message_eligible_for_history(msg)


def test_ambiguous_reference_skips_stale_topic_cards():
    app = _app()
    with app.app_context():
        db.create_all()
        user = User(email="ambig@test.com")
        user.set_password("password12")
        db.session.add(user)
        db.session.flush()
        thread = ChatThread(user_id=user.id, thread_type="agent_dm")
        db.session.add(thread)
        db.session.flush()

        db.session.add(ThreadTopic(
            thread_id=thread.id,
            title="EU AI regulation investment",
            summary="Discussed ASML, SAP, OVH for EU AI Act positioning.",
            key_insights=["Regulatory thematic basket"],
            keywords=["regulation", "stock", "eu", "ai"],
            status="active",
        ))
        db.session.add(ThreadTopic(
            thread_id=thread.id,
            title="High return stock picks",
            summary="Recommended NVDA, META, AMZN, GOOGL, MSFT for growth.",
            key_insights=["Maximize return focus"],
            keywords=["stock", "return", "growth"],
            status="active",
        ))
        for role, content in [
            ("user", "Recommend 5 stocks that maximize return"),
            ("assistant", "I'd buy NVDA, META, AMZN, GOOGL, MSFT."),
            ("user", "Which stocks did you recommend?"),
        ]:
            db.session.add(ChatMessage(thread_id=thread.id, role=role, content=content))
        db.session.commit()

        assert is_ambiguous_reference("Which stocks did you recommend?")
        ctx = build_memory_context(thread.id, "Which stocks did you recommend?")
        assert ctx.relevant_topics == []
        assert "DISAMBIGUATION" in ctx.memory_prompt_block
        assert "RECENT CONVERSATION" in ctx.memory_prompt_block
        assert "NVDA" in ctx.memory_prompt_block
        assert "EU AI regulation" not in ctx.memory_prompt_block.split("RECENT CONVERSATION")[1][:800]


def test_format_memory_prompt_block_lists_other_topics():
    block = format_memory_prompt_block(
        rolling_summary="Earlier we discussed budgets.",
        relevant_topics=[{"title": "Budget review", "summary": "Q3 budget", "key_insights": []}],
        topic_catalog=["Budget review", "Hiring plan", "Vendor audit"],
    )
    assert "LONG-TERM CONVERSATION SUMMARY" in block
    assert "Budget review" in block
    assert "OTHER TOPICS" in block
