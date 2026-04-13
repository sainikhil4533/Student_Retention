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
    ADD COLUMN IF NOT EXISTS external_student_ref VARCHAR(80),
    ADD COLUMN IF NOT EXISTS profile_context JSON;

    ALTER TABLE lms_events
    ADD COLUMN IF NOT EXISTS context_fields JSON;
    """

    with engine.begin() as connection:
        connection.execute(text(statement))

    print("vignan profile + LMS context columns are ready.")


if __name__ == "__main__":
    main()
