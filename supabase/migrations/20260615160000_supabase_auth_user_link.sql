-- Link app users to Supabase Auth (auth.users)

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS supabase_auth_id UUID UNIQUE;

CREATE INDEX IF NOT EXISTS ix_users_supabase_auth_id ON public.users (supabase_auth_id);

-- Passwords are managed by Supabase Auth when supabase_auth_id is set.
ALTER TABLE public.users
    ALTER COLUMN password_hash DROP NOT NULL;
