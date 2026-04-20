from __future__ import annotations

from dataclasses import dataclass

from src.api.auth import AuthContext
from src.api.copilot_memory import resolve_copilot_memory_context
from src.api.copilot_semantic_planner import plan_copilot_query_with_semantic_assist
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
) -> tuple[str, dict, dict]:
    query_plan, semantic_planner = plan_copilot_query_with_semantic_assist(
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
        query_plan=query_plan.to_dict(),
    )
    session_messages.append(
        _SessionRow(
            role="assistant",
            metadata_json={
                "memory_context": memory_context,
                "semantic_planner": semantic_planner,
            },
        )
    )
    return answer, memory_context, semantic_planner


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

        session: list[_SessionRow] = []
        turn_1, _memory_1, _semantic_1 = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="what is my current attendance",
            session_messages=session,
        )
        turn_2, _memory_2, semantic_2 = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="continue",
            session_messages=session,
        )
        turn_3, _memory_3, _semantic_3 = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="ok",
            session_messages=session,
        )
        turn_4, _memory_4, semantic_4 = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="proceed",
            session_messages=session,
        )
        turn_5, _memory_5, semantic_5 = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="proceed with overall recovery priorities",
            session_messages=session,
        )
        turn_6, _memory_6, semantic_6 = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="how can i recover from high alert",
            session_messages=session,
        )
        turn_7, _memory_7, semantic_7 = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt='in what way i can remove the "HIGH" label risk?',
            session_messages=session,
        )

        print("--- student turn 1 ---")
        print(turn_1)
        print("--- student turn 2 ---")
        print(turn_2)
        print(semantic_2)
        print("--- student turn 3 ---")
        print(turn_3)
        print("--- student turn 4 ---")
        print(turn_4)
        print(semantic_4)
        print("--- student turn 5 ---")
        print(turn_5)
        print(semantic_5)
        print("--- student turn 6 ---")
        print(turn_6)
        print(semantic_6)
        print("--- student turn 7 ---")
        print(turn_7)
        print(semantic_7)

        assert "overall attendance" in turn_1.lower()
        assert "eligibility" in turn_2.lower() or "i-grade" in turn_2.lower()
        assert "reduce your current high alert" in turn_3.lower() or "focus should be" in turn_3.lower()
        assert "day-by-day" in turn_4.lower() or "day by day" in turn_4.lower()
        assert semantic_4["provider"] == "local_fallback"
        assert "overall recovery" in turn_5.lower() or "reduce your current high alert" in turn_5.lower()
        assert semantic_5["provider"] in {"local_fallback", "gemini"} or semantic_5["status"] == "not_needed"
        assert "reduce your current high alert" in turn_6.lower() or "fastest recovery path" in turn_6.lower()
        assert semantic_6["provider"] in {"local_fallback", "gemini"} or semantic_6["status"] == "not_needed"
        assert "high label does not go away manually" in turn_7.lower() or "fastest recovery path" in turn_7.lower()
        assert semantic_7["provider"] in {"local_fallback", "gemini"} or semantic_7["status"] == "not_needed"

        print("Student dynamic action verify passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
