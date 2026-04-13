from pathlib import Path
import sys
from sqlalchemy import text


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.database import engine


DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS guardian_alert_events (
        id SERIAL PRIMARY KEY,
        student_id INTEGER NOT NULL,
        prediction_history_id INTEGER NOT NULL REFERENCES prediction_history(id),
        alert_type VARCHAR(50) NOT NULL,
        risk_level VARCHAR(20) NOT NULL,
        final_risk_probability DOUBLE PRECISION NOT NULL,
        guardian_name VARCHAR(255) NULL,
        guardian_relationship VARCHAR(50) NULL,
        recipient VARCHAR(255) NOT NULL,
        channel VARCHAR(30) NOT NULL,
        delivery_status VARCHAR(30) NOT NULL,
        retry_count INTEGER NOT NULL DEFAULT 0,
        error_message TEXT NULL,
        context_snapshot JSON NULL,
        sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_guardian_alert_events_student_id
    ON guardian_alert_events (student_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_guardian_alert_events_prediction_history_id
    ON guardian_alert_events (prediction_history_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_guardian_alert_events_alert_type
    ON guardian_alert_events (alert_type);
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_guardian_alert_events_channel
    ON guardian_alert_events (channel);
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_guardian_alert_events_delivery_status
    ON guardian_alert_events (delivery_status);
    """,
]


def main() -> None:
    with engine.begin() as connection:
        for statement in DDL_STATEMENTS:
            connection.execute(text(statement))
    print("guardian alert event table is ready.")


if __name__ == "__main__":
    main()
