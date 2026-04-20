from __future__ import annotations

from collections import Counter
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
    profiles = repository.get_imported_student_profiles_for_counsellor_identity(
        subject=auth.subject,
        display_name=auth.display_name,
    )
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
    session_messages.append(_SessionRow(role="assistant", metadata_json={"memory_context": memory_context}))
    return answer, memory_context


def main() -> None:
    db = SessionLocal()
    try:
        repository = EventRepository(db)
        imported_profiles = repository.get_imported_student_profiles()
        if not imported_profiles:
            raise SystemExit("No imported student profiles were found.")

        scoped_name = Counter(
            str(getattr(profile, "counsellor_name", "") or "").strip()
            for profile in imported_profiles
            if str(getattr(profile, "counsellor_name", "") or "").strip()
        ).most_common(1)
        if not scoped_name:
            raise SystemExit("No counsellor-assigned imported profiles were found.")

        counsellor_name = scoped_name[0][0]
        counsellor_auth = AuthContext(
            role="counsellor",
            subject=counsellor_name,
            display_name=counsellor_name,
            auth_provider="local_institution_account",
        )

        session: list[_SessionRow] = []
        risk_answer, _risk_memory = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt="which students are high risk",
            session_messages=session,
        )
        assigned_answer, assigned_memory = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt="show my assigned students",
            session_messages=session,
        )
        grade_answer, grade_memory = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt="which students have i grade risk",
            session_messages=session,
        )
        action_answer, action_memory = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt="what should i do for high risk students",
            session_messages=session,
        )

        print("--- counsellor risk answer ---")
        print(risk_answer)
        print("--- counsellor assigned answer ---")
        print(assigned_answer)
        print(assigned_memory)
        print("--- counsellor i-grade answer ---")
        print(grade_answer)
        print(grade_memory)
        print("--- counsellor action answer ---")
        print(action_answer)
        print(action_memory)

        assert "high-risk cohort" in risk_answer.lower()
        assert _risk_memory.get("response_type") == "data"
        assert _risk_memory.get("last_topic") == "high_risk_students"

        assigned_lowered = assigned_answer.lower()
        assert "clarification needed" not in assigned_lowered
        assert "assigned to your counsellor scope" in assigned_lowered
        assert "student_id" in assigned_lowered
        assert assigned_memory.get("response_type") == "data"
        assert assigned_memory.get("last_topic") == "assigned_students"

        grade_lowered = grade_answer.lower()
        assert "clarification needed" not in grade_lowered
        assert "i-grade" in grade_lowered
        assert "students in your current counsellor scope" in grade_lowered or "counsellor review" in grade_lowered
        assert grade_memory.get("response_type") == "data"
        assert grade_memory.get("last_topic") == "i_grade_risk"

        action_lowered = action_answer.lower()
        assert "clarification needed" not in action_lowered
        assert "grounded operational action list" in action_lowered or "action list" in action_lowered
        assert action_memory.get("pending_role_follow_up") == "operational_actions"
        assert action_memory.get("response_type") == "action"
        assert action_memory.get("last_topic") == "cohort_actions"

        followup_session: list[_SessionRow] = []
        first_answer, first_memory = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt="show my assigned students",
            session_messages=followup_session,
        )
        second_answer, second_memory = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt="yes",
            session_messages=followup_session,
        )
        print("--- counsellor assigned follow-up first turn ---")
        print(first_answer)
        print(first_memory)
        print("--- counsellor assigned follow-up second turn ---")
        print(second_answer)
        print(second_memory)
        assert second_memory.get("response_type") == "action"
        assert second_memory.get("last_topic") == "cohort_actions"
        assert "grounded operational action list" in second_answer.lower()

        print("Counsellor topic-switch live verification passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
