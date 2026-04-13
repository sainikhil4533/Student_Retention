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
        ALTER TABLE student_profiles
        ADD COLUMN IF NOT EXISTS student_email VARCHAR(255);
        """,
        """
        CREATE TABLE IF NOT EXISTS student_warning_events (
            id SERIAL PRIMARY KEY,
            student_id INTEGER NOT NULL,
            prediction_history_id INTEGER NOT NULL REFERENCES prediction_history(id),
            warning_type VARCHAR(50) NOT NULL,
            risk_level VARCHAR(20) NOT NULL,
            final_risk_probability DOUBLE PRECISION NOT NULL,
            recipient VARCHAR(255) NOT NULL,
            delivery_status VARCHAR(20) NOT NULL,
            error_message TEXT NULL,
            sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            recovery_deadline TIMESTAMPTZ NOT NULL,
            resolved_at TIMESTAMPTZ NULL,
            resolution_status VARCHAR(30) NULL
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_student_warning_events_student_id
        ON student_warning_events (student_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_student_warning_events_prediction_history_id
        ON student_warning_events (prediction_history_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_student_warning_events_warning_type
        ON student_warning_events (warning_type);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_student_warning_events_delivery_status
        ON student_warning_events (delivery_status);
        """,
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

    print("Student warning support schema is ready.")


if __name__ == "__main__":
    main()
