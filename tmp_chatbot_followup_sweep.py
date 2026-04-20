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

        student_session: list[_SessionRow] = []
        student_answer, _ = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="Can you plan my next few weeks?",
            session_messages=student_session,
        )
        student_followup, _ = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="yes, break it down",
            session_messages=student_session,
        )
        student_attendance_session: list[_SessionRow] = []
        student_attendance_answer, student_attendance_memory = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="what is my current attendance",
            session_messages=student_attendance_session,
        )
        student_attendance_followup, _ = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="ok tell",
            session_messages=student_attendance_session,
        )

        admin_session: list[_SessionRow] = []
        admin_answer, admin_memory = _run_turn(
            repository=repository,
            auth=admin_auth,
            prompt="Show attendance risk branch wise.",
            session_messages=admin_session,
        )
        admin_followup, _ = _run_turn(
            repository=repository,
            auth=admin_auth,
            prompt="only CSE",
            session_messages=admin_session,
        )

        counsellor_session: list[_SessionRow] = []
        counsellor_answer, counsellor_memory = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt="Show attendance risk gender wise.",
            session_messages=counsellor_session,
        )
        counsellor_followup, _ = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt="only Female",
            session_messages=counsellor_session,
        )

        print("--- student first turn ---")
        print(student_answer)
        print("--- student follow-up ---")
        print(student_followup)
        print("--- student attendance first turn ---")
        print(student_attendance_answer)
        print(student_attendance_memory)
        print("--- student attendance follow-up ---")
        print(student_attendance_followup)
        print("--- admin first turn ---")
        print(admin_answer)
        print(admin_memory)
        print("--- admin follow-up ---")
        print(admin_followup)
        print("--- counsellor first turn ---")
        print(counsellor_answer)
        print(counsellor_memory)
        print("--- counsellor follow-up ---")
        print(counsellor_followup)

        assert "this week" in student_answer.lower()
        assert "attendance" in student_followup.lower() or "coursework" in student_followup.lower() or "overall recovery" in student_followup.lower()
        assert student_attendance_memory.get("pending_student_follow_up") == "attendance_territory"
        assert "i-grade" in student_attendance_followup.lower() or "r-grade" in student_attendance_followup.lower() or "eligibility" in student_attendance_followup.lower()

        assert admin_memory.get("kind") == "import_coverage"
        assert admin_memory.get("grouped_by") == "branch"
        assert "focused the previous grouped result" in admin_followup.lower() or "updated the previous grouped result" in admin_followup.lower()
        assert "matching students" in admin_followup.lower()

        assert counsellor_memory.get("kind") == "import_coverage"
        assert counsellor_memory.get("grouped_by") == "gender"
        assert "focused the previous grouped result" in counsellor_followup.lower() or "updated the previous grouped result" in counsellor_followup.lower()
        assert "matching students" in counsellor_followup.lower()

        print("Chatbot follow-up sweep passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
