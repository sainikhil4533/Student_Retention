from pathlib import Path
import sys

from sqlalchemy import text


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.database import engine


def main() -> None:
    statement = """
    ALTER TABLE student_profiles
    ADD COLUMN IF NOT EXISTS parent_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS parent_relationship VARCHAR(50),
    ADD COLUMN IF NOT EXISTS parent_email VARCHAR(255),
    ADD COLUMN IF NOT EXISTS parent_phone VARCHAR(30),
    ADD COLUMN IF NOT EXISTS preferred_guardian_channel VARCHAR(30),
    ADD COLUMN IF NOT EXISTS guardian_contact_enabled BOOLEAN NOT NULL DEFAULT FALSE;
    """

    with engine.begin() as connection:
        connection.execute(text(statement))

    print("guardian contact columns are ready in student_profiles.")


if __name__ == "__main__":
    main()
