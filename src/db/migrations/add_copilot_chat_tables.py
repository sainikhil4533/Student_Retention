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
        CREATE TABLE IF NOT EXISTS copilot_chat_sessions (
            id SERIAL PRIMARY KEY,
            owner_subject VARCHAR(255) NOT NULL,
            owner_role VARCHAR(30) NOT NULL,
            owner_student_id INTEGER NULL,
            display_name VARCHAR(255) NULL,
            title VARCHAR(255) NOT NULL DEFAULT 'New chat',
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            system_prompt_version VARCHAR(30) NOT NULL DEFAULT 'cb1',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_message_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_copilot_chat_sessions_owner_subject
        ON copilot_chat_sessions (owner_subject);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_copilot_chat_sessions_owner_role
        ON copilot_chat_sessions (owner_role);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_copilot_chat_sessions_owner_student_id
        ON copilot_chat_sessions (owner_student_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_copilot_chat_sessions_status
        ON copilot_chat_sessions (status);
        """,
        """
        CREATE TABLE IF NOT EXISTS copilot_chat_messages (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES copilot_chat_sessions(id) ON DELETE CASCADE,
            role VARCHAR(20) NOT NULL,
            message_type VARCHAR(30) NOT NULL DEFAULT 'text',
            content TEXT NOT NULL,
            metadata_json JSON NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_copilot_chat_messages_session_id
        ON copilot_chat_messages (session_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_copilot_chat_messages_role
        ON copilot_chat_messages (role);
        """,
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

    print("copilot chat tables are ready.")


if __name__ == "__main__":
    main()
