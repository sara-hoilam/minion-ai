"""Apply lightweight SQLite schema migrations for existing databases."""

from sqlalchemy import inspect, text

from backend.models import db


def migrate_db() -> None:
    if db.engine.dialect.name != "sqlite":
        db.create_all()
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        if "users" in tables:
            cols = {c["name"] for c in inspector.get_columns("users")}
            if "supabase_auth_id" not in cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS supabase_auth_id UUID"))
                db.session.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_supabase_auth_id ON users (supabase_auth_id)"
                ))
        db.session.commit()
        return

    db.create_all()
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()

    if "users" in tables:
        cols = {c["name"] for c in inspector.get_columns("users")}
        if "supabase_auth_id" not in cols:
            col_type = "VARCHAR(36)" if db.engine.dialect.name == "sqlite" else "UUID"
            db.session.execute(text(f"ALTER TABLE users ADD COLUMN supabase_auth_id {col_type}"))

    if "user_profiles" in tables:
        cols = {c["name"] for c in inspector.get_columns("user_profiles")}
        for col, col_type in [
            ("resume_file_path", "VARCHAR(500)"),
            ("resume_original_name", "VARCHAR(255)"),
            ("resume_uploaded_at", "DATETIME"),
        ]:
            if col not in cols:
                db.session.execute(text(f"ALTER TABLE user_profiles ADD COLUMN {col} {col_type}"))

    if "studio_sessions" in tables:
        cols = {c["name"] for c in inspector.get_columns("studio_sessions")}
        if "agent_generated_at" not in cols:
            db.session.execute(text("ALTER TABLE studio_sessions ADD COLUMN agent_generated_at DATETIME"))
        if "agent_context" not in cols:
            db.session.execute(text("ALTER TABLE studio_sessions ADD COLUMN agent_context JSON"))

    if "chat_threads" in tables:
        cols = {c["name"] for c in inspector.get_columns("chat_threads")}
        for col, col_type in [
            ("thread_type", "VARCHAR(20) DEFAULT 'agent_dm'"),
            ("project_id", "INTEGER"),
            ("participant_agent_ids", "JSON"),
            ("pinned", "BOOLEAN DEFAULT 0"),
            ("cursor_cloud_agent_id", "VARCHAR(64)"),
            ("is_generating", "BOOLEAN DEFAULT 0"),
            ("cancel_requested", "BOOLEAN DEFAULT 0"),
            ("generation_progress", "JSON"),
            ("active_cursor_run", "JSON"),
            ("generation_seq", "INTEGER DEFAULT 0"),
            ("pending_plan", "JSON"),
        ]:
            if col not in cols:
                db.session.execute(text(f"ALTER TABLE chat_threads ADD COLUMN {col} {col_type}"))

    if "thread_memory_states" in tables:
        cols = {c["name"] for c in inspector.get_columns("thread_memory_states")}
        if "compaction_status" not in cols:
            db.session.execute(
                text("ALTER TABLE thread_memory_states ADD COLUMN compaction_status VARCHAR(20) DEFAULT 'idle'")
            )

    db.create_all()

    db.session.commit()
