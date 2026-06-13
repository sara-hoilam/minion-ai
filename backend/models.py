from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Uuid
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    supabase_auth_id = db.Column(Uuid(as_uuid=False), unique=True, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    stripe_customer_id = db.Column(db.String(255))
    subscription_status = db.Column(db.String(50), default="trialing")

    profile = db.relationship("UserProfile", back_populates="user", uselist=False)
    studio_sessions = db.relationship("StudioSession", back_populates="user")
    agent_artifacts = db.relationship("AgentArtifact", back_populates="user")
    events = db.relationship("Event", back_populates="user")
    subscription = db.relationship(
        "UserSubscription",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def uses_supabase_auth(self) -> bool:
        return bool(self.supabase_auth_id)


class UserProfile(db.Model):
    __tablename__ = "user_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    full_name = db.Column(db.String(255))
    field = db.Column(db.String(100))
    skillset = db.Column(db.Text)
    current_job = db.Column(db.String(255))
    years_experience = db.Column(db.Integer)
    industry = db.Column(db.String(100))
    completed_background = db.Column(db.Boolean, default=False)
    resume_file_path = db.Column(db.String(500))
    resume_original_name = db.Column(db.String(255))
    resume_uploaded_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    user = db.relationship("User", back_populates="profile")


class StudioSession(db.Model):
    __tablename__ = "studio_sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    studio_template = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(50), default="in_progress")
    current_task_index = db.Column(db.Integer, default=0)
    started_at = db.Column(db.DateTime, default=utcnow)
    completed_at = db.Column(db.DateTime)
    agent_generated_at = db.Column(db.DateTime)
    agent_context = db.Column(db.JSON)

    user = db.relationship("User", back_populates="studio_sessions")
    task_responses = db.relationship("TaskResponse", back_populates="session", cascade="all, delete-orphan")


class TaskResponse(db.Model):
    __tablename__ = "task_responses"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("studio_sessions.id"), nullable=False)
    task_id = db.Column(db.String(100), nullable=False)
    task_type = db.Column(db.String(50))
    response_data = db.Column(db.JSON, nullable=False)
    time_spent_seconds = db.Column(db.Integer)
    revision_count = db.Column(db.Integer, default=0)
    submitted_at = db.Column(db.DateTime, default=utcnow)

    session = db.relationship("StudioSession", back_populates="task_responses")


class AgentArtifact(db.Model):
    __tablename__ = "agent_artifacts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey("studio_sessions.id"))
    artifact_type = db.Column(db.String(50), nullable=False)
    file_path = db.Column(db.String(500))
    content_preview = db.Column(db.Text)
    generated_at = db.Column(db.DateTime, default=utcnow)

    user = db.relationship("User", back_populates="agent_artifacts")


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    session_id = db.Column(db.String(100), index=True)
    event_type = db.Column(db.String(100), nullable=False, index=True)
    payload = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=utcnow, index=True)

    user = db.relationship("User", back_populates="events")


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    instructions = db.Column(db.Text)
    agent_session_ids = db.Column(db.JSON, default=list)
    context_files = db.Column(db.JSON, default=list)
    pinned = db.Column(db.Boolean, default=False)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    threads = db.relationship("ChatThread", back_populates="project", cascade="all, delete-orphan")


class ChatThread(db.Model):
    __tablename__ = "chat_threads"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    thread_type = db.Column(db.String(20), default="agent_dm", index=True)  # agent_dm | project | project_agent
    agent_session_id = db.Column(db.Integer, db.ForeignKey("studio_sessions.id"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), index=True)
    participant_agent_ids = db.Column(db.JSON)
    title = db.Column(db.String(255))
    pinned = db.Column(db.Boolean, default=False)
    cursor_cloud_agent_id = db.Column(db.String(64))
    is_generating = db.Column(db.Boolean, default=False)
    cancel_requested = db.Column(db.Boolean, default=False)
    generation_progress = db.Column(db.JSON)
    active_cursor_run = db.Column(db.JSON)
    generation_seq = db.Column(db.Integer, default=0)
    pending_plan = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    project = db.relationship("Project", back_populates="threads")
    messages = db.relationship("ChatMessage", back_populates="thread", cascade="all, delete-orphan")


class ChatMessage(db.Model):
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True)
    thread_id = db.Column(db.Integer, db.ForeignKey("chat_threads.id"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)  # user | assistant | system
    content = db.Column(db.Text, nullable=False)
    meta = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=utcnow)

    thread = db.relationship("ChatThread", back_populates="messages")


class ThreadMemoryState(db.Model):
    """Rolling summary + compaction cursor for a chat thread (Supabase: thread_memory_states)."""

    __tablename__ = "thread_memory_states"

    id = db.Column(db.Integer, primary_key=True)
    thread_id = db.Column(db.Integer, db.ForeignKey("chat_threads.id"), unique=True, nullable=False, index=True)
    rolling_summary = db.Column(db.Text, default="")
    summary_through_message_id = db.Column(db.Integer, default=0)
    summary_file_path = db.Column(db.String(500))
    topics_file_path = db.Column(db.String(500))
    last_compacted_at = db.Column(db.DateTime)
    compaction_status = db.Column(db.String(20), default="idle")
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    thread = db.relationship("ChatThread", backref=db.backref("memory_state", uselist=False))


class ThreadTopic(db.Model):
    """Long-term topic memory per thread (Supabase: thread_topics + optional pgvector on embedding)."""

    __tablename__ = "thread_topics"

    id = db.Column(db.Integer, primary_key=True)
    thread_id = db.Column(db.Integer, db.ForeignKey("chat_threads.id"), nullable=False, index=True)
    agent_session_id = db.Column(db.Integer, db.ForeignKey("studio_sessions.id"), index=True)
    title = db.Column(db.String(255), nullable=False)
    summary = db.Column(db.Text, default="")
    key_insights = db.Column(db.JSON, default=list)
    keywords = db.Column(db.JSON, default=list)
    source_message_ids = db.Column(db.JSON, default=list)
    # JSON float array today; migrate to pgvector(1536) when on Supabase
    embedding = db.Column(db.JSON)
    status = db.Column(db.String(20), default="active", index=True)
    last_referenced_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    thread = db.relationship("ChatThread", backref=db.backref("topics", lazy="dynamic"))


class AgentFeedback(db.Model):
    __tablename__ = "agent_feedback"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
    agent_session_id = db.Column(db.Integer, db.ForeignKey("studio_sessions.id"), nullable=False, index=True)
    thread_id = db.Column(db.Integer, db.ForeignKey("chat_threads.id"), nullable=True)
    content = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="pending", index=True)
    filter_score = db.Column(db.Float)
    filter_reason = db.Column(db.Text)
    filter_categories = db.Column(db.JSON, default=list)
    applied_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow)

    project = db.relationship("Project", backref=db.backref("feedback_entries", lazy="dynamic"))


class UserSubscription(db.Model):
    __tablename__ = "user_subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False, index=True)
    plan_id = db.Column(db.String(50), nullable=False, default="starter")
    stripe_subscription_id = db.Column(db.String(255), index=True)
    stripe_price_id = db.Column(db.String(255))
    status = db.Column(db.String(50), nullable=False, default="inactive")
    token_budget_usd = db.Column(db.Numeric(12, 4), nullable=False, default=0)
    token_used_usd = db.Column(db.Numeric(12, 4), nullable=False, default=0)
    current_period_start = db.Column(db.DateTime)
    current_period_end = db.Column(db.DateTime)
    cancel_at_period_end = db.Column(db.Boolean, default=False, nullable=False)
    cancelled_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    user = db.relationship("User", back_populates="subscription")

    @property
    def token_remaining_usd(self) -> float:
        return max(0.0, float(self.token_budget_usd or 0) - float(self.token_used_usd or 0))


class BillingEvent(db.Model):
    __tablename__ = "billing_events"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    event_type = db.Column(db.String(80), nullable=False)
    plan_id = db.Column(db.String(50))
    amount_usd = db.Column(db.Numeric(10, 2))
    token_delta_usd = db.Column(db.Numeric(12, 4))
    stripe_event_id = db.Column(db.String(255), unique=True, nullable=True)
    payload = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=utcnow)

    user = db.relationship("User", backref=db.backref("billing_events", lazy="dynamic"))


class LlmUsageEvent(db.Model):
    __tablename__ = "llm_usage_events"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    thread_id = db.Column(db.Integer, db.ForeignKey("chat_threads.id"), index=True)
    session_id = db.Column(db.Integer, db.ForeignKey("studio_sessions.id"), index=True)
    cursor_agent_id = db.Column(db.String(64), nullable=False)
    cursor_run_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    model = db.Column(db.String(80))
    source = db.Column(db.String(80), nullable=False, default="chat")
    run_status = db.Column(db.String(32))
    input_tokens = db.Column(db.Integer, nullable=False, default=0)
    output_tokens = db.Column(db.Integer, nullable=False, default=0)
    cache_read_tokens = db.Column(db.Integer, nullable=False, default=0)
    cache_write_tokens = db.Column(db.Integer, nullable=False, default=0)
    total_tokens = db.Column(db.Integer, nullable=False, default=0)
    cost_usd = db.Column(db.Numeric(12, 6), nullable=False, default=0)
    billed_usd = db.Column(db.Numeric(12, 6), nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=utcnow)

    user = db.relationship("User", backref=db.backref("llm_usage_events", lazy="dynamic"))
