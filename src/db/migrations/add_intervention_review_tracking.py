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
        ALTER TABLE intervention_actions
        ADD COLUMN IF NOT EXISTS alert_validity VARCHAR(30) NULL;
        """,
        """
        ALTER TABLE intervention_actions
        ADD COLUMN IF NOT EXISTS false_alert_reason TEXT NULL;
        """,
        """
        ALTER TABLE intervention_actions
        ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(255) NULL;
        """,
        """
        ALTER TABLE intervention_actions
        ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ NULL;
        """,
        """
        ALTER TABLE intervention_actions
        ADD COLUMN IF NOT EXISTS outcome_status VARCHAR(30) NULL;
        """,
        """
        ALTER TABLE intervention_actions
        ADD COLUMN IF NOT EXISTS outcome_notes TEXT NULL;
        """,
        """
        ALTER TABLE intervention_actions
        ADD COLUMN IF NOT EXISTS outcome_recorded_by VARCHAR(255) NULL;
        """,
        """
        ALTER TABLE intervention_actions
        ADD COLUMN IF NOT EXISTS outcome_recorded_at TIMESTAMPTZ NULL;
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_intervention_actions_alert_validity
        ON intervention_actions (alert_validity);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_intervention_actions_outcome_status
        ON intervention_actions (outcome_status);
        """,
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

    print("Intervention review and outcome tracking support is ready.")


if __name__ == "__main__":
    main()
