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
        ALTER TABLE prediction_history
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
        """,
        """
        CREATE TABLE IF NOT EXISTS alert_events (
            id SERIAL PRIMARY KEY,
            student_id INTEGER NOT NULL,
            prediction_history_id INTEGER NOT NULL REFERENCES prediction_history(id),
            alert_type VARCHAR(50) NOT NULL,
            risk_level VARCHAR(20) NOT NULL,
            final_risk_probability DOUBLE PRECISION NOT NULL,
            recipient VARCHAR(255) NOT NULL,
            email_status VARCHAR(20) NOT NULL,
            error_message TEXT NULL,
            sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_alert_events_student_id
        ON alert_events (student_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_alert_events_prediction_history_id
        ON alert_events (prediction_history_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_alert_events_alert_type
        ON alert_events (alert_type);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_alert_events_email_status
        ON alert_events (email_status);
        """,
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

    print("Alert support schema is ready.")


if __name__ == "__main__":
    main()
