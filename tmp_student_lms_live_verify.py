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
        risk_answer, _risk_memory, _risk_semantic = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="am i falling into risk zone or not",
            session_messages=session,
        )
        lms_details_answer, lms_details_memory, lms_details_semantic = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="what is my LMS details",
            session_messages=session,
        )
        lms_activity_answer, lms_activity_memory, lms_activity_semantic = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="give me my lms activity",
            session_messages=session,
        )
        lms_followup_answer, lms_followup_memory, lms_followup_semantic = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="ok",
            session_messages=session,
        )

        print("--- risk answer ---")
        print(risk_answer)
        print("--- lms details answer ---")
        print(lms_details_answer)
        print(lms_details_memory)
        print(lms_details_semantic)
        print("--- lms activity answer ---")
        print(lms_activity_answer)
        print(lms_activity_memory)
        print(lms_activity_semantic)
        print("--- lms follow-up answer ---")
        print(lms_followup_answer)
        print(lms_followup_memory)
        print(lms_followup_semantic)

        assert "latest risk level" in risk_answer.lower()

        lms_details_lowered = lms_details_answer.lower()
        assert "clarification needed" not in lms_details_lowered
        assert "lms" in lms_details_lowered
        assert "clicks in the last 7 days" in lms_details_lowered
        assert "unique lms resources" in lms_details_lowered
        assert "latest risk level is high" not in lms_details_lowered
        assert lms_details_memory.get("pending_student_follow_up") == "lms_risk_explanation"

        lms_activity_lowered = lms_activity_answer.lower()
        assert "clarification needed" not in lms_activity_lowered
        assert "lms" in lms_activity_lowered
        assert "clicks in the last 7 days" in lms_activity_lowered
        assert "didn’t fully match" not in lms_activity_lowered
        assert lms_activity_memory.get("pending_student_follow_up") == "lms_risk_explanation"

        lms_followup_lowered = lms_followup_answer.lower()
        assert "clarification needed" not in lms_followup_lowered
        assert "lms pattern" in lms_followup_lowered or "lms snapshot" in lms_followup_lowered
        assert "risk" in lms_followup_lowered
        assert lms_followup_memory.get("pending_student_follow_up") == "student_action_list"

        print("Student LMS live verification passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
