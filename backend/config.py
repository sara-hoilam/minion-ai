import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-in-production")
SUPABASE_URL = os.getenv(
    "SUPABASE_URL",
    "https://icqipnezzvsqxmjgeonx.supabase.co",
).strip()
SUPABASE_PROJECT_REF = os.getenv("SUPABASE_PROJECT_REF", "icqipnezzvsqxmjgeonx").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "project-context").strip()
APP_URL = os.getenv("APP_URL", "http://localhost:5000").strip().rstrip("/")

_default_db = f"sqlite:///{BASE_DIR / 'minion.db'}"


def _normalize_database_url(url: str) -> str:
    """Use pg8000 on Windows/Python 3.14 where psycopg2 wheels are unavailable."""
    if url.startswith("postgresql+") or url.startswith("sqlite:"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+pg8000://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+pg8000://", 1)
    return url


_database_url = _normalize_database_url(os.getenv("DATABASE_URL", _default_db))
SQLALCHEMY_DATABASE_URI = _database_url
SQLALCHEMY_TRACK_MODIFICATIONS = False
# Optional second URL (Supabase session pooler) for migrations / admin scripts
DATABASE_DIRECT_URL = os.getenv("DATABASE_DIRECT_URL", "").strip()

# Postgres pool settings when DATABASE_URL points at Supabase
_engine_opts: dict = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}
if _database_url.startswith("postgresql") and ":6543" in _database_url:
    # Transaction-mode pooler: keep the app-side pool small
    _engine_opts["pool_size"] = 5
    _engine_opts["max_overflow"] = 2
SQLALCHEMY_ENGINE_OPTIONS = _engine_opts
UPLOAD_FOLDER = BASE_DIR / "uploads"
RESUME_UPLOAD_FOLDER = UPLOAD_FOLDER / "resumes"
AGENT_OUTPUT_FOLDER = BASE_DIR / "agent_outputs"
MEMORY_FOLDER = BASE_DIR / "memory"

# Conversation memory (short-term window + summarization thresholds)
MEMORY_SHORT_TERM_MESSAGES = int(os.getenv("MEMORY_SHORT_TERM_MESSAGES", "12"))
MEMORY_SUMMARIZE_BATCH = int(os.getenv("MEMORY_SUMMARIZE_BATCH", "16"))
MEMORY_TOPIC_RELEVANCE_TOP_K = int(os.getenv("MEMORY_TOPIC_RELEVANCE_TOP_K", "3"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


CURSOR_API_KEY = os.getenv("CURSOR_API_KEY", "").strip()
CURSOR_API_BASE = os.getenv("CURSOR_API_BASE", "https://api.cursor.com")
CURSOR_MODEL = os.getenv("CURSOR_MODEL", "composer-2.5")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

SUBSCRIPTION_PRICE_DISPLAY = "$49/mo"

# Set to false in production. When true, auto-logs in a demo user — no login required.
DISABLE_AUTH = os.getenv("DISABLE_AUTH", "false").lower() in ("1", "true", "yes")
