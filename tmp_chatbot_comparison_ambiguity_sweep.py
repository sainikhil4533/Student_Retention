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

        cases = [
            (
                "admin ambiguity",
                admin_auth,
                "What is the difference between prediction risk and attendance risk?",
                ["prediction risk", "attendance-policy risk", "active academic burden"],
            ),
            (
                "counsellor ambiguity",
                counsellor_auth,
                "What is the difference between prediction risk and attendance risk for my students?",
                ["prediction risk", "attendance-policy risk", "your current counsellor scope"],
            ),
            (
                "admin comparison",
                admin_auth,
                "Compare Male vs Female high-risk students.",
                ["I compared", "Male", "Female", "prediction high risk"],
            ),
            (
                "counsellor comparison",
                counsellor_auth,
                "Compare Male vs Female high-risk students.",
                ["I compared", "Male", "Female", "prediction high risk"],
            ),
            (
                "admin attention analysis",
                admin_auth,
                "Which region is worse and why?",
                ["strongest retention pressure", "Why:", "region"],
            ),
            (
                "counsellor diagnostic comparison",
                counsellor_auth,
                "Which gender is worse and why?",
                ["strongest retention pressure", "Primary driver", "Why:"],
            ),
        ]

        for label, auth, prompt, expected_fragments in cases:
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

        follow_up_session: list[_SessionRow] = []
        first_answer, first_memory = _run_turn(
            repository=repository,
            auth=admin_auth,
            prompt="Compare Male vs Female high-risk students.",
            session_messages=follow_up_session,
        )
        follow_up_answer, _ = _run_turn(
            repository=repository,
            auth=admin_auth,
            prompt="only Female",
            session_messages=follow_up_session,
        )
        print("--- admin comparison first turn ---")
        print(first_answer)
        print(first_memory)
        print("--- admin comparison follow-up ---")
        print(follow_up_answer)
        assert first_memory.get("kind") == "import_coverage"
        assert first_memory.get("grouped_by") == "gender"
        assert "focused the previous grouped result" in follow_up_answer.lower() or "updated the previous grouped result" in follow_up_answer.lower()
        assert "matching students" in follow_up_answer.lower()

        print("Chatbot comparison and ambiguity sweep passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
