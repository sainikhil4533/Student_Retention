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

        one_turn_cases = [
            (
                "student safety wording",
                student_auth,
                "am i safe or should i worry?",
                ["attendance", "risk"],
            ),
            (
                "student what should i do first",
                student_auth,
                "what exactly is hurting me most and what should i do first?",
                ["weakest", "focus"],
            ),
            (
                "student older uncleared burden",
                student_auth,
                "do i still have any uncleared grade issue from older sems?",
                ["uncleared", "grade"],
            ),
            (
                "counsellor weekly unresolved monitoring",
                counsellor_auth,
                "even if they are doing fine now, who still needs weekly monitoring?",
                ["weekly", "burden"],
            ),
            (
                "counsellor grouped semester",
                counsellor_auth,
                "show my students high risk semester wise",
                ["semester-wise breakdown"],
            ),
            (
                "admin grouped natural high risk",
                admin_auth,
                "can you show me all the students who are at high risk semester wise, year wise",
                ["generic 'high risk' can mean either", "semester-wise breakdown", "year-wise breakdown"],
            ),
        ]

        for label, auth, prompt, expected_fragments in one_turn_cases:
            answer, _ = _run_turn(
                repository=repository,
                auth=auth,
                prompt=prompt,
                session_messages=[],
            )
            lowered = answer.lower()
            print(f"--- {label}: {prompt} ---")
            print(answer)
            for fragment in expected_fragments:
                assert fragment.lower() in lowered, f"Missing fragment `{fragment}` for case `{label}`"

        admin_session: list[_SessionRow] = []
        first_answer, first_memory = _run_turn(
            repository=repository,
            auth=admin_auth,
            prompt="can you show me all the students who are at high risk semester wise, year wise",
            session_messages=admin_session,
        )
        second_answer, _ = _run_turn(
            repository=repository,
            auth=admin_auth,
            prompt="branch wise also",
            session_messages=admin_session,
        )
        print("--- admin follow-up first turn ---")
        print(first_answer)
        print(first_memory)
        print("--- admin follow-up branch wise also ---")
        print(second_answer)
        assert "branch" in second_answer.lower()

        print("Live chatbot UAT sweep passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
