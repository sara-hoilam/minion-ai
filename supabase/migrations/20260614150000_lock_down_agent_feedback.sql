-- agent_feedback was added after the initial RLS lock-down migration.

ALTER TABLE public.agent_feedback ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.agent_feedback FROM anon, authenticated;

CREATE INDEX IF NOT EXISTS ix_agent_feedback_user_id ON agent_feedback (user_id);
