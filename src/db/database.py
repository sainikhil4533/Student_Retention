from pathlib import Path
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(ENV_PATH)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set. Please update the .env file.")

if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine_kwargs = {"future": True}

# Supabase pooler / PgBouncer-style connections can fail when psycopg auto-prepares
# statements across reused pooled sessions. Disabling prepared statements keeps
# repeated API requests stable in this deployment mode.
if DATABASE_URL.startswith("postgresql+psycopg://"):
    engine_kwargs["connect_args"] = {
        "prepare_threshold": None,
        "connect_timeout": 5,
    }

# The Supabase pooler is already the real connection pool. Keeping an extra
# small SQLAlchemy pool on top of it can make the app look healthy at first and
# then degrade after a few slow requests, because long-lived chat/page requests
# can pin the tiny local pool. Using NullPool here avoids that local bottleneck
# and lets the remote pooler own connection reuse.
if ".pooler.supabase.com:6543/" in DATABASE_URL:
    engine_kwargs["poolclass"] = NullPool

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
