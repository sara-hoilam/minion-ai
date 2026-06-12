-- Project workspace: per-agent threads, agent feedback, storage bucket

CREATE TABLE IF NOT EXISTS agent_feedback (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    agent_session_id INTEGER NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
    thread_id INTEGER REFERENCES chat_threads(id) ON DELETE SET NULL,
    content TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    filter_score DOUBLE PRECISION,
    filter_reason TEXT,
    filter_categories JSONB DEFAULT '[]'::jsonb,
    applied_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_agent_feedback_agent_status ON agent_feedback (agent_session_id, status);
CREATE INDEX IF NOT EXISTS ix_agent_feedback_project_created ON agent_feedback (project_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS ix_chat_threads_project_agent
    ON chat_threads (user_id, project_id, agent_session_id)
    WHERE thread_type = 'project_agent';

INSERT INTO storage.buckets (id, name, public)
VALUES ('project-context', 'project-context', false)
ON CONFLICT (id) DO NOTHING;
