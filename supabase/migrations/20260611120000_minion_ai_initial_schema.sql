-- Minion AI initial schema (Flask-SQLAlchemy compatible)
-- Project: MinionAI-DB (icqipnezzvsqxmjgeonx)

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    stripe_customer_id VARCHAR(255),
    subscription_status VARCHAR(50) DEFAULT 'trialing'
);
CREATE INDEX ix_users_email ON users (email);

CREATE TABLE user_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    full_name VARCHAR(255),
    field VARCHAR(100),
    skillset TEXT,
    current_job VARCHAR(255),
    years_experience INTEGER,
    industry VARCHAR(100),
    completed_background BOOLEAN DEFAULT FALSE,
    resume_file_path VARCHAR(500),
    resume_original_name VARCHAR(255),
    resume_uploaded_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE studio_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    studio_template VARCHAR(100) NOT NULL,
    status VARCHAR(50) DEFAULT 'in_progress',
    current_task_index INTEGER DEFAULT 0,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    agent_generated_at TIMESTAMPTZ,
    agent_context JSONB
);

CREATE TABLE task_responses (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
    task_id VARCHAR(100) NOT NULL,
    task_type VARCHAR(50),
    response_data JSONB NOT NULL,
    time_spent_seconds INTEGER,
    revision_count INTEGER DEFAULT 0,
    submitted_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE agent_artifacts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id INTEGER REFERENCES studio_sessions(id) ON DELETE SET NULL,
    artifact_type VARCHAR(50) NOT NULL,
    file_path VARCHAR(500),
    content_preview TEXT,
    generated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    session_id VARCHAR(100),
    event_type VARCHAR(100) NOT NULL,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_events_user_id ON events (user_id);
CREATE INDEX ix_events_session_id ON events (session_id);
CREATE INDEX ix_events_event_type ON events (event_type);
CREATE INDEX ix_events_created_at ON events (created_at);

CREATE TABLE projects (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    instructions TEXT,
    agent_session_ids JSONB DEFAULT '[]'::jsonb,
    context_files JSONB DEFAULT '[]'::jsonb,
    pinned BOOLEAN DEFAULT FALSE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_projects_user_id ON projects (user_id);

CREATE TABLE chat_threads (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_type VARCHAR(20) DEFAULT 'agent_dm',
    agent_session_id INTEGER REFERENCES studio_sessions(id) ON DELETE SET NULL,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    participant_agent_ids JSONB,
    title VARCHAR(255),
    pinned BOOLEAN DEFAULT FALSE,
    cursor_cloud_agent_id VARCHAR(64),
    is_generating BOOLEAN DEFAULT FALSE,
    cancel_requested BOOLEAN DEFAULT FALSE,
    generation_progress JSONB,
    active_cursor_run JSONB,
    generation_seq INTEGER DEFAULT 0,
    pending_plan JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_chat_threads_user_id ON chat_threads (user_id);
CREATE INDEX ix_chat_threads_thread_type ON chat_threads (thread_type);
CREATE INDEX ix_chat_threads_agent_session_id ON chat_threads (agent_session_id);
CREATE INDEX ix_chat_threads_project_id ON chat_threads (project_id);

CREATE TABLE chat_messages (
    id SERIAL PRIMARY KEY,
    thread_id INTEGER NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    meta JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_chat_messages_thread_id ON chat_messages (thread_id);

CREATE TABLE thread_memory_states (
    id SERIAL PRIMARY KEY,
    thread_id INTEGER NOT NULL UNIQUE REFERENCES chat_threads(id) ON DELETE CASCADE,
    rolling_summary TEXT DEFAULT '',
    summary_through_message_id INTEGER DEFAULT 0,
    summary_file_path VARCHAR(500),
    topics_file_path VARCHAR(500),
    last_compacted_at TIMESTAMPTZ,
    compaction_status VARCHAR(20) DEFAULT 'idle',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_thread_memory_states_thread_id ON thread_memory_states (thread_id);

CREATE TABLE thread_topics (
    id SERIAL PRIMARY KEY,
    thread_id INTEGER NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
    agent_session_id INTEGER REFERENCES studio_sessions(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    summary TEXT DEFAULT '',
    key_insights JSONB DEFAULT '[]'::jsonb,
    keywords JSONB DEFAULT '[]'::jsonb,
    source_message_ids JSONB DEFAULT '[]'::jsonb,
    embedding JSONB,
    embedding_vector extensions.vector(1536),
    status VARCHAR(20) DEFAULT 'active',
    last_referenced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_thread_topics_thread_id ON thread_topics (thread_id);
CREATE INDEX ix_thread_topics_agent_session_id ON thread_topics (agent_session_id);
CREATE INDEX ix_thread_topics_status ON thread_topics (status);
CREATE INDEX ix_thread_topics_embedding_vector ON thread_topics
    USING hnsw (embedding_vector extensions.vector_cosine_ops);
