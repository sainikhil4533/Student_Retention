from __future__ import annotations

from dataclasses import dataclass

from src.api.auth import AuthContext
from src.api.copilot_memory import resolve_copilot_memory_context
from src.api.copilot_planner import plan_copilot_query
from src.api.copilot_tools import generate_grounded_copilot_answer
from src.db.database import SessionLocal
from src.db.repository import EventRepository


@dataclass
class _SessionRow:
    role: str
    metadata_json: dict


def _run_turn(*, repository: EventRepository, auth: AuthContext, prompt: str, session_messages: list[_SessionRow]) -> tuple[str, dict]:
    profiles = None
    if auth.role == "admin":
        profiles = repository.get_imported_student_profiles()
    elif auth.role == "counsellor":
        profiles = repository.get_imported_student_profiles_for_counsellor_identity(
            subject=auth.subject,
            display_name=auth.display_name,
        )
    plan = plan_copilot_query(
        role=auth.role,
        message=prompt,
        session_messages=session_messages,
        profiles=profiles,
    )
    memory = resolve_copilot_memory_context(message=prompt, session_messages=session_messages)
    answer, _tools_used, _limitations, memory_context = generate_grounded_copilot_answer(
        auth=auth,
        repository=repository,
        message=prompt,
        session_messages=session_messages,
        memory=memory,
        query_plan=plan.to_dict(),
    )
    session_messages.append(_SessionRow(role="assistant", metadata_json={"memory_context": memory_context}))
    return answer, memory_context


def main() -> None:
    db = SessionLocal()
    try:
        repository = EventRepository(db)
        counsellor_auth = AuthContext(
            role="counsellor",
            subject="asha.counsellor",
            student_id=None,
            display_name="Counsellor Asha",
            auth_provider="local_institution_account",
        )
        admin_auth = AuthContext(
            role="admin",
            subject="admin.retention",
            student_id=None,
            display_name="Retention Admin",
            auth_provider="local_institution_account",
        )

        counsellor_session: list[_SessionRow] = []
        counsellor_answer_1, _ = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt="show my students high risk semester wise",
            session_messages=counsellor_session,
        )
        counsellor_answer_2, _ = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt="continue",
            session_messages=counsellor_session,
        )
        print("--- counsellor smoke turn 1 ---")
        print(counsellor_answer_1)
        print("--- counsellor smoke turn 2 ---")
        print(counsellor_answer_2)
        assert "semester-wise breakdown" in counsellor_answer_1.lower()
        assert "operational action list" in counsellor_answer_2.lower()

        admin_session: list[_SessionRow] = []
        admin_answer_1, _ = _run_turn(
            repository=repository,
            auth=admin_auth,
            prompt="which branch needs attention first and why",
            session_messages=admin_session,
        )
        admin_answer_2, _ = _run_turn(
            repository=repository,
            auth=admin_auth,
            prompt="ok",
            session_messages=admin_session,
        )
        print("--- admin smoke turn 1 ---")
        print(admin_answer_1)
        print("--- admin smoke turn 2 ---")
        print(admin_answer_2)
        assert "needs attention first" in admin_answer_1.lower()
        assert "institution-level action list" in admin_answer_2.lower()

        print("Role operational live smoke passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
