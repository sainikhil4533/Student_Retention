from pathlib import Path
import sys

from sqlalchemy import text


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.database import engine


def main() -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS background_jobs (
            id SERIAL PRIMARY KEY,
            job_type VARCHAR(50) NOT NULL,
            dedupe_key VARCHAR(255) NULL,
            payload JSONB NOT NULL,
            status VARCHAR(20) NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NULL,
            available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            claimed_at TIMESTAMPTZ NULL,
            completed_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_background_jobs_job_type
        ON background_jobs (job_type);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_background_jobs_dedupe_key
        ON background_jobs (dedupe_key);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_background_jobs_status
        ON background_jobs (status);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_background_jobs_available_at
        ON background_jobs (available_at);
        """,
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

    print("Background jobs support is ready.")


if __name__ == "__main__":
    main()
