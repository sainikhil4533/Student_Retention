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


def _run_turn(
    *,
    repository: EventRepository,
    auth: AuthContext,
    prompt: str,
    session_messages: list[_SessionRow],
) -> tuple[str, dict]:
    plan = plan_copilot_query(
        role=auth.role,
        message=prompt,
        session_messages=session_messages,
        profiles=[],
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
        imported_profiles = repository.get_imported_student_profiles()
        if not imported_profiles:
            raise SystemExit("No imported student profiles were found.")

        student_profile = imported_profiles[0]
        student_auth = AuthContext(
            role="student",
            subject="stu001",
            student_id=int(student_profile.student_id),
            display_name=str(student_profile.external_student_ref or "Student"),
            auth_provider="local_institution_account",
        )

        session_messages: list[_SessionRow] = []
        first_answer, first_memory = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="how are my assignment rate",
            session_messages=session_messages,
        )
        second_answer, second_memory = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="ok",
            session_messages=session_messages,
        )

        print("--- assignment rate answer ---")
        print(first_answer)
        print(first_memory)
        print("--- follow-up answer ---")
        print(second_answer)
        print(second_memory)

        first_lowered = first_answer.lower()
        assert "clarification needed" not in first_lowered
        assert "assignment submission rate" in first_lowered
        assert "current weighted assessment score" in first_lowered
        assert first_memory.get("pending_student_follow_up") == "coursework_risk_explanation"

        second_lowered = second_answer.lower()
        assert "clarification needed" not in second_lowered
        assert "affecting your risk" in second_lowered or "latest prediction risk view" in second_lowered

        print("Student assignment-rate live verification passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
