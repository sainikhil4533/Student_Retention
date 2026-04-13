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
        ALTER TABLE alert_events
        ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
        """,
        """
        ALTER TABLE student_warning_events
        ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
        """,
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

    print("Email retry tracking support is ready.")


if __name__ == "__main__":
    main()
