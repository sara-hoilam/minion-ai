-- Minion AI: Flask connects via postgres pooler (server-side).
-- Block Supabase Data API (anon/authenticated) from reading app tables.

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.studio_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.task_responses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_threads ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.thread_memory_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.thread_topics ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated;
