from pathlib import Path
import os
import time

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(ENV_PATH)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set. Please update the .env file.")

if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine_kwargs: dict = {"future": True}

# Disable prepared statements — pgBouncer (Supabase pooler) does not support them.
if DATABASE_URL.startswith("postgresql+psycopg://"):
    engine_kwargs["connect_args"] = {
        "prepare_threshold": None,
        "connect_timeout": 30,
    }

# Connection strategy:
# Background workers are DISABLED on Free Tier, so only the API process connects.
# QueuePool(3+2) keeps up to 5 warm connections — eliminating the 500ms TCP+SSL
# overhead on EVERY query that NullPool incurs.
#
# pool_recycle=90   — recycle before Supabase's ~120s idle timeout kills connections
# pool_pre_ping=True — test connection before use to survive any transient kills
# pool_timeout=20   — wait up to 20s for a free connection before raising
#
# 5 connections << 15 (Supabase Free Tier limit) — safe margin.
if ".pooler.supabase.com" in DATABASE_URL:
    from sqlalchemy.pool import QueuePool
    engine_kwargs["poolclass"] = QueuePool
    engine_kwargs["pool_size"] = 5
    engine_kwargs["max_overflow"] = 5
    engine_kwargs["pool_recycle"] = 90
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_timeout"] = 30

engine = create_engine(DATABASE_URL, **engine_kwargs)

# Mark Supabase-specific transient errors as disconnects so the pool
# discards broken connections and opens fresh ones automatically.
from sqlalchemy import event

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
        )
        if any(marker in err_msg for marker in disconnect_markers):
            exception_context.is_disconnect = True

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_with_retry(fn, max_retries=3, label="db_operation"):
    """Run fn(db) with a fresh session, retrying on transient Supabase errors.
    Sessions are always closed after each attempt regardless of outcome.
    """
    last_error = None
    for attempt in range(1, max_retries + 1):
        db = SessionLocal()
        try:
            result = fn(db)
            return result
        except Exception as e:
            last_error = e
            try:
                db.rollback()
            except Exception:
                pass
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
            )
            is_transient = any(m in err_text for m in transient_markers)
            if is_transient and attempt < max_retries:
                wait = 3.0 * attempt
                print(
                    f"[{label}] transient DB error (attempt {attempt}/{max_retries}), "
                    f"retrying in {wait}s: {type(e).__name__}",
                    flush=True,
                )
                time.sleep(wait)
                continue
            raise
        finally:
            try:
                db.close()
            except Exception:
                pass
    raise last_error  # type: ignore[misc]
