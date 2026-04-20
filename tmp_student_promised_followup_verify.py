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
            prompt="what is my current attendance",
            session_messages=session_messages,
        )
        second_answer, second_memory = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="ok tell",
            session_messages=session_messages,
        )
        third_answer, third_memory = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="Ok",
            session_messages=session_messages,
        )
        why_answer, why_memory = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="my current attendance is in SAFE mode right but why i have been put into HIGH alert?",
            session_messages=[],
        )

        print("--- first turn ---")
        print(first_answer)
        print(first_memory)
        print("--- follow-up ---")
        print(second_answer)
        print(second_memory)
        print("--- second follow-up ---")
        print(third_answer)
        print(third_memory)
        print("--- safe attendance but high alert ---")
        print(why_answer)
        print(why_memory)

        assert first_memory.get("pending_student_follow_up") == "attendance_territory"
        lowered = second_answer.lower()
        assert "i-grade" in lowered or "r-grade" in lowered or "eligibility" in lowered
        assert "did you mean" not in lowered
        third_lowered = third_answer.lower()
        assert "focus" in third_lowered or "recovery" in third_lowered or "attendance" in third_lowered
        assert "did you mean" not in third_lowered
        why_lowered = why_answer.lower()
        assert "high alert" in why_lowered or "high risk" in why_lowered
        assert "attendance currently looks safe" in why_lowered or "not contradictory" in why_lowered
        assert "dominant cross-signal explanation" in why_lowered
        assert why_memory.get("intent") == "student_self_subject_risk"

        print("Student promised follow-up verification passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
