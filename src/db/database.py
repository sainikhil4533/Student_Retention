from pathlib import Path
from contextlib import contextmanager
import os
import time
from urllib.parse import urlparse, urlunparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(ENV_PATH)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set. Please update the .env file.")

_IS_SUPABASE_POOLER = ".pooler.supabase.com" in DATABASE_URL

if _IS_SUPABASE_POOLER:
    pooler_mode = os.getenv("RETENTIONOS_SUPABASE_POOLER_MODE", "session").strip().lower()
    if pooler_mode == "session":
        parsed_url = urlparse(DATABASE_URL)
        if parsed_url.hostname and parsed_url.port == 6543:
            netloc = parsed_url.netloc.rsplit(":", 1)[0] + ":5432"
            DATABASE_URL = urlunparse(parsed_url._replace(netloc=netloc))

if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value in (None, ""):
        return default
    try:
        return int(str(raw_value).strip())
    except ValueError:
        return default


engine_kwargs: dict = {"future": True}

# Disable prepared statements; pgBouncer (Supabase pooler) does not support them.
if DATABASE_URL.startswith("postgresql+psycopg://"):
    engine_kwargs["connect_args"] = {
        "prepare_threshold": None,
        "connect_timeout": _env_int("RETENTIONOS_DB_CONNECT_TIMEOUT_SECONDS", 5),
        "options": (
            f"-c statement_timeout={_env_int('RETENTIONOS_DB_STATEMENT_TIMEOUT_MS', 15000)} "
            f"-c idle_in_transaction_session_timeout={_env_int('RETENTIONOS_DB_IDLE_TX_TIMEOUT_MS', 15000)}"
        ),
    }

# Use QueuePool to allow concurrent DB access across all modules.
# Supabase Free Tier allows ~15 concurrent connections.
# pool_size=8 keeps 8 idle connections ready; max_overflow=7 allows bursting to 15.
# pool_recycle=180 prevents stale connections (Supabase idles out at ~300s;
#   use a shorter recycle to recover faster after project pause/resume).
# pool_pre_ping=True validates connections before use (avoids "connection closed" errors).
# pool_reset_on_return="rollback" ensures connections are clean when returned to pool.
engine_kwargs["poolclass"] = QueuePool
engine_kwargs["pool_size"] = _env_int("RETENTIONOS_DB_POOL_SIZE", 8)
engine_kwargs["max_overflow"] = _env_int("RETENTIONOS_DB_MAX_OVERFLOW", 7)
engine_kwargs["pool_recycle"] = 180
engine_kwargs["pool_pre_ping"] = True
engine_kwargs["pool_timeout"] = 10
engine_kwargs["pool_reset_on_return"] = "rollback"

engine = create_engine(DATABASE_URL, **engine_kwargs)

# Mark Supabase-specific transient errors as disconnects so the pool
# discards broken connections and opens fresh ones automatically.
@event.listens_for(engine, "handle_error")
def handle_supabase_errors(exception_context):
    if exception_context.original_exception:
        err_msg = str(exception_context.original_exception).lower()
        disconnect_markers = (
            "dbhandler exited",
            "unable to check out connection",
            "server closed the connection",
            "connection timeout expired",
            "consuming input failed",
            "connection was reset",
            "broken pipe",
            "ssl connection has been closed",
            "connection refused",
            "maxclientsinsessionmode",
        )
        if any(marker in err_msg for marker in disconnect_markers):
            exception_context.is_disconnect = True

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


@contextmanager
def db_session_scope():
    """Open a short-lived DB session. No serialization lock — QueuePool handles concurrency."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            db.close()
        except Exception:
            pass


def get_db():
    with db_session_scope() as db:
        yield db


def run_with_retry(fn, max_retries=3, label="db_operation"):
    """Run fn(db) with a fresh session, retrying on transient Supabase errors.
    Sessions are always closed after each attempt regardless of outcome.
    """
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            with db_session_scope() as db:
                return fn(db)
        except Exception as e:
            last_error = e
            err_text = str(e).lower()
            transient_markers = (
                "dbhandler exited",
                "server closed the connection",
                "connection timeout expired",
                "consuming input failed",
                "unable to check out connection",
                "connection was reset",
                "broken pipe",
                "operational",
                "maxclientsinsessionmode",
                "max client connections reached",
            )
            is_transient = any(m in err_text for m in transient_markers)
            if is_transient and attempt < max_retries:
                wait = 2.0 * attempt
                print(
                    f"[{label}] transient DB error (attempt {attempt}/{max_retries}), "
                    f"retrying in {wait}s: {type(e).__name__}",
                    flush=True,
                )
                time.sleep(wait)
                continue
            raise
    raise last_error  # type: ignore[misc]
