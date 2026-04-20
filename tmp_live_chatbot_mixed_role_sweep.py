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
    profiles = None
    if auth.role == "admin":
        profiles = repository.get_imported_student_profiles()
    elif auth.role == "counsellor":
        profiles = repository.get_imported_student_profiles_for_counsellor_identity(
            subject=auth.subject,
            display_name=auth.display_name,
        )
    query_plan, semantic_planner = plan_copilot_query_with_semantic_assist(
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
        student_turn_1, student_memory_1, student_semantic_1 = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="what is my current attendance",
            session_messages=student_session,
        )
        student_turn_2, student_memory_2, student_semantic_2 = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="ok tell",
            session_messages=student_session,
        )
        student_turn_3, _student_memory_3, student_semantic_3 = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="and why exactly?",
            session_messages=student_session,
        )
        print("--- student turn 1 ---")
        print(student_turn_1)
        print(student_semantic_1)
        print("--- student turn 2 ---")
        print(student_turn_2)
        print(student_semantic_2)
        print(student_memory_2)
        print("--- student turn 3 ---")
        print(student_turn_3)
        print(student_semantic_3)
        assert "overall attendance" in student_turn_1.lower()
        assert student_semantic_2["provider"] == "local_fallback"
        assert "i-grade" in student_turn_2.lower() or "r-grade" in student_turn_2.lower() or "eligibility" in student_turn_2.lower()
        assert student_semantic_3["provider"] == "local_fallback"
        assert "dominant cross-signal explanation" in student_turn_3.lower() or "strongest current drivers" in student_turn_3.lower()

        admin_session: list[_SessionRow] = []
        admin_turn_1, _admin_memory_1, admin_semantic_1 = _run_turn(
            repository=repository,
            auth=admin_auth,
            prompt="can you show me all the students who are at high risk semester wise, year wise",
            session_messages=admin_session,
        )
        admin_turn_2, _admin_memory_2, admin_semantic_2 = _run_turn(
            repository=repository,
            auth=admin_auth,
            prompt="branch wise also",
            session_messages=admin_session,
        )
        admin_turn_3, _admin_memory_3, admin_semantic_3 = _run_turn(
            repository=repository,
            auth=admin_auth,
            prompt="what do you mean by that?",
            session_messages=admin_session,
        )
        print("--- admin turn 1 ---")
        print(admin_turn_1)
        print(admin_semantic_1)
        print("--- admin turn 2 ---")
        print(admin_turn_2)
        print(admin_semantic_2)
        print("--- admin turn 3 ---")
        print(admin_turn_3)
        print(admin_semantic_3)
        assert "semester-wise breakdown" in admin_turn_1.lower()
        assert "year-wise breakdown" in admin_turn_1.lower()
        assert admin_semantic_2["provider"] == "local_fallback"
        assert "branch-wise breakdown" in admin_turn_2.lower()
        assert admin_semantic_3["provider"] == "local_fallback"
        assert "prediction risk" in admin_turn_3.lower() and "attendance-policy risk" in admin_turn_3.lower()

        counsellor_monitoring_turn, _counsellor_monitoring_memory, counsellor_monitoring_semantic = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt="even if they look okay now, who still needs weekly monitoring",
            session_messages=[],
        )
        print("--- counsellor monitoring turn ---")
        print(counsellor_monitoring_turn)
        print(counsellor_monitoring_semantic)
        assert counsellor_monitoring_semantic["provider"] == "local_fallback"
        assert "weekly" in counsellor_monitoring_turn.lower() and "burden" in counsellor_monitoring_turn.lower()

        counsellor_grouped_session: list[_SessionRow] = []
        counsellor_turn_1, _counsellor_memory_1, counsellor_semantic_1 = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt="show attendance risk gender wise",
            session_messages=counsellor_grouped_session,
        )
        counsellor_turn_2, _counsellor_memory_2, counsellor_semantic_2 = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt="what about only Female",
            session_messages=counsellor_grouped_session,
        )
        counsellor_turn_3, _counsellor_memory_3, counsellor_semantic_3 = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt="semester wise also",
            session_messages=counsellor_grouped_session,
        )
        print("--- counsellor grouped turn 1 ---")
        print(counsellor_turn_1)
        print(counsellor_semantic_1)
        print("--- counsellor grouped turn 2 ---")
        print(counsellor_turn_2)
        print(counsellor_semantic_2)
        print("--- counsellor grouped turn 3 ---")
        print(counsellor_turn_3)
        print(counsellor_semantic_3)
        assert "gender-wise breakdown" in counsellor_turn_1.lower()
        assert counsellor_semantic_2["provider"] == "local_fallback"
        assert "matching students" in counsellor_turn_2.lower()
        assert counsellor_semantic_3["provider"] == "local_fallback"
        assert "semester-wise breakdown" in counsellor_turn_3.lower()

        print("Live chatbot mixed-role sweep passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
