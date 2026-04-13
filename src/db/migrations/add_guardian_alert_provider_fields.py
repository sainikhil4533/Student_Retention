from pathlib import Path
import sys

from sqlalchemy import text


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.database import engine


def main() -> None:
    statement = """
    ALTER TABLE guardian_alert_events
    ADD COLUMN IF NOT EXISTS provider_name VARCHAR(50),
    ADD COLUMN IF NOT EXISTS provider_message_id VARCHAR(255);
    """

    with engine.begin() as connection:
        connection.execute(text(statement))

    print("guardian alert provider fields are ready.")


if __name__ == "__main__":
    main()
