from __future__ import annotations

from src.api.auth import AuthContext
from src.api.copilot_memory import resolve_copilot_memory_context
from src.api.copilot_planner import plan_copilot_query
from src.api.copilot_tools import generate_grounded_copilot_answer
from src.db.database import SessionLocal
from src.db.repository import EventRepository


def _run_prompt(
    *,
    repository: EventRepository,
    auth: AuthContext,
    prompt: str,
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
        session_messages=[],
        profiles=profiles,
    )
    memory = resolve_copilot_memory_context(message=prompt, session_messages=[])
    answer, _tools_used, _limitations, _memory_context = generate_grounded_copilot_answer(
        auth=auth,
        repository=repository,
        message=prompt,
        session_messages=[],
        memory=memory,
        query_plan=plan.to_dict(),
    )
    return answer


def main() -> None:
    db = SessionLocal()
    try:
        repository = EventRepository(db)
        imported_profiles = repository.get_imported_student_profiles()
        if not imported_profiles:
            raise SystemExit("No imported student profiles were found.")

        admin_auth = AuthContext(
            role="admin",
            subject="admin.retention",
            student_id=None,
            display_name="Retention Admin",
            auth_provider="local_institution_account",
        )
        counsellor_auth = AuthContext(
            role="counsellor",
            subject="asha.counsellor",
            student_id=None,
            display_name="Counsellor Asha",
            auth_provider="local_institution_account",
        )

        cases = [
            (
                admin_auth,
                "Show attendance risk branch wise.",
                ["branch-wise breakdown", "overall shortage"],
            ),
            (
                admin_auth,
                "Show prediction high risk region wise.",
                ["region-wise breakdown", "prediction high risk"],
            ),
            (
                admin_auth,
                "Show attendance risk category wise.",
                ["category-wise breakdown", "i-grade"],
            ),
            (
                admin_auth,
                "Show prediction high risk and attendance risk income wise.",
                ["income-wise breakdown", "prediction high risk", "r-grade"],
            ),
            (
                admin_auth,
                "Show prediction high risk status wise.",
                ["status-wise breakdown", "prediction high risk"],
            ),
            (
                admin_auth,
                "Show attendance risk gender wise.",
                ["gender-wise breakdown", "overall shortage"],
            ),
            (
                admin_auth,
                "Show prediction high risk program wise.",
                ["program-wise breakdown", "prediction high risk"],
            ),
            (
                admin_auth,
                "Show attendance risk batch wise.",
                ["batch-wise breakdown", "i-grade"],
            ),
            (
                admin_auth,
                "Show prediction high risk and attendance risk age band wise.",
                ["age-band-wise breakdown", "prediction high risk", "r-grade"],
            ),
            (
                admin_auth,
                "Show prediction high risk and attendance risk branch wise, semester wise and year wise.",
                ["branch-wise breakdown", "semester-wise breakdown", "year-wise breakdown"],
            ),
            (
                counsellor_auth,
                "Show attendance risk branch wise.",
                ["branch-wise breakdown", "your current counsellor scope"],
            ),
            (
                counsellor_auth,
                "Show prediction high risk semester wise and year wise.",
                ["semester-wise breakdown", "year-wise breakdown", "your current counsellor scope"],
            ),
            (
                counsellor_auth,
                "Show attendance risk gender wise.",
                ["gender-wise breakdown", "your current counsellor scope"],
            ),
        ]

        for auth, prompt, expected_fragments in cases:
            answer = _run_prompt(repository=repository, auth=auth, prompt=prompt)
            lowered = answer.lower()
            print(f"--- {auth.role}: {prompt} ---")
            print(answer)
            for fragment in expected_fragments:
                assert fragment.lower() in lowered, f"Missing fragment `{fragment}` for prompt: {prompt}"
            if prompt == "Show attendance risk branch wise.":
                assert "grouped prediction-high-risk breakdown" not in lowered
                assert "prediction high risk is currently" not in lowered
            if prompt == "Show attendance risk category wise.":
                assert "grouped prediction-high-risk breakdown" not in lowered
                assert "prediction high risk is currently" not in lowered
            if prompt == "Show attendance risk gender wise.":
                assert "grouped prediction-high-risk breakdown" not in lowered
                assert "prediction high risk is currently" not in lowered
            if prompt == "Show attendance risk batch wise.":
                assert "grouped prediction-high-risk breakdown" not in lowered
                assert "prediction high risk is currently" not in lowered

        print("Grouped risk prompt sweep passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
