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
        CREATE TABLE IF NOT EXISTS faculty_summary_snapshots (
            id SERIAL PRIMARY KEY,
            snapshot_type VARCHAR(30) NOT NULL,
            summary_payload JSONB NOT NULL,
            generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_faculty_summary_snapshots_snapshot_type
        ON faculty_summary_snapshots (snapshot_type);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_faculty_summary_snapshots_generated_at
        ON faculty_summary_snapshots (generated_at);
        """,
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

    print("Faculty summary snapshot schema is ready.")


if __name__ == "__main__":
    main()
