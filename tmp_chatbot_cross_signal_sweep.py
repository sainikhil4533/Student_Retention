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
) -> str:
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
    return answer


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

        counsellor_profiles = repository.get_imported_student_profiles_for_counsellor_identity(
            subject=counsellor_auth.subject,
            display_name=counsellor_auth.display_name,
        )
        if not counsellor_profiles:
            raise SystemExit("No counsellor-scoped student profiles were found.")
        counsellor_student_id = int(counsellor_profiles[0].student_id)
        admin_student_id = int(imported_profiles[0].student_id)

        cases = [
            (
                "student inventory",
                student_auth,
                "What data do you have about me?",
                ["prediction data is available", "lms engagement data", "erp academic-performance data", "finance context"],
            ),
            (
                "student safety reconciliation",
                student_auth,
                "Am I safe or should I worry?",
                ["latest prediction risk view", "dominant cross-signal explanation", "strongest current drivers"],
            ),
            (
                "counsellor drilldown cross-signal",
                counsellor_auth,
                f"show details for student {counsellor_student_id}",
                ["dominant cross-signal explanation", "lms snapshot", "erp snapshot"],
            ),
            (
                "admin drilldown cross-signal",
                admin_auth,
                f"show details for student {admin_student_id}",
                ["dominant cross-signal explanation", "lms snapshot", "erp snapshot"],
            ),
        ]

        for label, auth, prompt, fragments in cases:
            answer = _run_turn(
                repository=repository,
                auth=auth,
                prompt=prompt,
                session_messages=[],
            )
            lowered = answer.lower()
            print(f"--- {label}: {prompt} ---")
            print(answer)
            for fragment in fragments:
                assert fragment.lower() in lowered, f"Missing fragment `{fragment}` for case `{label}`"

        print("Chatbot cross-signal sweep passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
