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
        ALTER TABLE faculty_summary_snapshots
        ADD COLUMN IF NOT EXISTS email_delivery_status VARCHAR(20) NULL;
        """,
        """
        ALTER TABLE faculty_summary_snapshots
        ADD COLUMN IF NOT EXISTS email_error_message TEXT NULL;
        """,
        """
        ALTER TABLE faculty_summary_snapshots
        ADD COLUMN IF NOT EXISTS emailed_at TIMESTAMPTZ NULL;
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_faculty_summary_snapshots_email_delivery_status
        ON faculty_summary_snapshots (email_delivery_status);
        """,
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

    print("Faculty summary snapshot email tracking schema is ready.")


if __name__ == "__main__":
    main()
