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
        CREATE TABLE IF NOT EXISTS intervention_actions (
            id SERIAL PRIMARY KEY,
            student_id INTEGER NOT NULL,
            alert_event_id INTEGER NULL REFERENCES alert_events(id),
            action_status VARCHAR(30) NOT NULL,
            actor_name VARCHAR(255) NULL,
            notes TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_intervention_actions_student_id
        ON intervention_actions (student_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_intervention_actions_alert_event_id
        ON intervention_actions (alert_event_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_intervention_actions_action_status
        ON intervention_actions (action_status);
        """,
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

    print("Intervention actions schema is ready.")


if __name__ == "__main__":
    main()
