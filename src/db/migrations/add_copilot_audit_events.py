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
        CREATE TABLE IF NOT EXISTS copilot_audit_events (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES copilot_chat_sessions(id) ON DELETE CASCADE,
            message_id INTEGER NULL REFERENCES copilot_chat_messages(id) ON DELETE SET NULL,
            owner_subject VARCHAR(255) NOT NULL,
            owner_role VARCHAR(30) NOT NULL,
            owner_student_id INTEGER NULL,
            detected_intent VARCHAR(60) NULL,
            resolved_intent VARCHAR(60) NULL,
            memory_applied BOOLEAN NOT NULL DEFAULT false,
            tool_summaries JSON NULL,
            refusal_reason VARCHAR(120) NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_copilot_audit_events_session_id
        ON copilot_audit_events (session_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_copilot_audit_events_owner_subject
        ON copilot_audit_events (owner_subject);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_copilot_audit_events_owner_role
        ON copilot_audit_events (owner_role);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_copilot_audit_events_owner_student_id
        ON copilot_audit_events (owner_student_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_copilot_audit_events_created_at
        ON copilot_audit_events (created_at);
        """,
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

    print("copilot audit events table is ready.")


if __name__ == "__main__":
    main()
