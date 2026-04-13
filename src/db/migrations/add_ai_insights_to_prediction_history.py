from pathlib import Path
import sys

from sqlalchemy import text


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.database import engine


def main() -> None:
    statement = """
    ALTER TABLE prediction_history
    ADD COLUMN IF NOT EXISTS ai_insights JSON;
    """

    with engine.begin() as connection:
        connection.execute(text(statement))

    print("ai_insights column is ready in prediction_history.")


if __name__ == "__main__":
    main()
