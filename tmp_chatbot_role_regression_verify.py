from __future__ import annotations

import sys
from pathlib import Path

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
    memory = resolve_copilot_memory_context(message=prompt, session_messages=[])
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
    answer, _tools_used, _limitations, _memory_context = generate_grounded_copilot_answer(
        auth=auth,
        repository=repository,
        message=prompt,
        session_messages=[],
        memory=memory,
        query_plan=plan.to_dict(),
    )
    return answer


LOG_PATH = Path(__file__).with_name("tmp_chatbot_role_regression_verify.log")


def _log(message: str) -> None:
    sys.stdout.reconfigure(line_buffering=True)
    print(message)
    LOG_PATH.write_text(
        ((LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else "") + message + "\n"),
        encoding="utf-8",
    )


def main() -> None:
    if LOG_PATH.exists():
        LOG_PATH.unlink()
    db = SessionLocal()
    try:
        repository = EventRepository(db)
        _log("loaded repository")
        imported_profiles = repository.get_imported_student_profiles()
        if not imported_profiles:
            raise SystemExit("No imported student profiles were found.")
        _log(f"imported_profiles={len(imported_profiles)}")

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

        _log("running student prompt")
        student_answer = _run_prompt(
            repository=repository,
            auth=student_auth,
            prompt="Do I still have any uncleared I grade or R grade subjects?",
        )
        _log("running counsellor prompt")
        counsellor_answer = _run_prompt(
            repository=repository,
            auth=counsellor_auth,
            prompt="Which of my students need weekly monitoring because of unresolved R grade burden?",
        )
        _log("running admin prompt")
        admin_answer = _run_prompt(
            repository=repository,
            auth=admin_auth,
            prompt="Show prediction high risk and attendance risk branch wise, semester wise and year wise.",
        )
        _log("all prompts completed")

        student_lower = student_answer.lower()
        counsellor_lower = counsellor_answer.lower()
        admin_lower = admin_answer.lower()

        print("--- student answer ---")
        print(student_answer)
        print("--- counsellor answer ---")
        print(counsellor_answer)
        print("--- admin answer ---")
        print(admin_answer)

        assert "uncleared" in student_lower or "pending r-grade clearance" in student_lower or "pending i-grade clearance" in student_lower
        assert "i-grade" in student_lower or "r-grade" in student_lower

        assert "weekly" in counsellor_lower
        assert "unresolved r-grade" in counsellor_lower or "r-grade burden" in counsellor_lower or "r-grade" in counsellor_lower
        assert "student_id" in counsellor_lower or "students" in counsellor_lower

        assert "semester-wise breakdown" in admin_lower
        assert "year-wise breakdown" in admin_lower
        assert "branch-wise breakdown" in admin_lower
        assert "prediction high risk" in admin_lower
        assert "i-grade" in admin_lower
        assert "r-grade" in admin_lower

        print("Chatbot role regression verification passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
