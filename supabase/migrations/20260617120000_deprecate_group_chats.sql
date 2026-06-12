-- Deprecate group chat threads (UI removed). Existing rows are kept for history.

COMMENT ON COLUMN chat_threads.thread_type IS
  'agent_dm | project | project_agent — group deprecated, no new group threads';
