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


def _run_turn(*, auth: AuthContext, prompt: str, session_messages: list[_SessionRow]) -> tuple[str, dict]:
    db = SessionLocal()
    try:
        repository = EventRepository(db)
        profiles = repository.get_imported_student_profiles()
        query_plan = plan_copilot_query(
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
            query_plan=query_plan.to_dict(),
        )
    finally:
        db.close()
    session_messages.append(_SessionRow(role="assistant", metadata_json={"memory_context": memory_context}))
    return answer, memory_context


def main() -> None:
    admin_auth = AuthContext(
        role="admin",
        subject="admin.retention",
        display_name="Retention Admin",
        auth_provider="local_institution_account",
    )
    grouped_session: list[_SessionRow] = []
    grouped_answer, grouped_memory = _run_turn(
        auth=admin_auth,
        prompt="branch-wise risk",
        session_messages=grouped_session,
    )
    only_cse_answer, only_cse_memory = _run_turn(
        auth=admin_auth,
        prompt="only CSE",
        session_messages=grouped_session,
    )
    continue_answer, continue_memory = _run_turn(
        auth=admin_auth,
        prompt="continue",
        session_messages=grouped_session,
    )
    print("--- branch-wise risk ---")
    print(grouped_answer)
    print(grouped_memory)
    print("--- only CSE ---")
    print(only_cse_answer)
    print(only_cse_memory)
    print("--- continue ---")
    print(continue_answer)
    print(continue_memory)
    assert "branch-wise breakdown" in grouped_answer.lower()
    assert "matching students" in only_cse_answer.lower()
    assert "institution-level action list" in continue_answer.lower()
    print("Admin follow-up verifier passed.")


if __name__ == "__main__":
    main()
