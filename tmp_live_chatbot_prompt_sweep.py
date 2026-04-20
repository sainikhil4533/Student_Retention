from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from src.api.auth import AuthContext
from src.api.copilot_memory import resolve_copilot_memory_context
from src.api.copilot_planner import plan_copilot_query
from src.api.copilot_tools import generate_grounded_copilot_answer
from src.db.database import SessionLocal
from src.db.repository import EventRepository

LOG_PATH = Path(__file__).with_name("tmp_live_chatbot_prompt_sweep.log")


def _log(message: str) -> None:
    sys.stdout.reconfigure(line_buffering=True)
    print(message)
    LOG_PATH.write_text(
        ((LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else "") + message + "\n"),
        encoding="utf-8",
    )


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
    if LOG_PATH.exists():
        LOG_PATH.unlink()
    sys.stdout.reconfigure(line_buffering=True)
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

        cases = [
            (
                "student",
                student_auth,
                "What data do you have about me?",
                ["attendance", "subject-wise", "risk"],
            ),
            (
                "student",
                student_auth,
                "What is my attendance right now?",
                ["overall attendance", "current visible semester"],
            ),
            (
                "student",
                student_auth,
                "Which subject is hurting me most right now?",
                ["weakest", "%"],
            ),
            (
                "student",
                student_auth,
                "Am I eligible for end sem?",
                ["end-sem", "eligible"],
            ),
            (
                "student",
                student_auth,
                "Do I still have any uncleared I grade or R grade subjects?",
                ["uncleared", "i-grade", "r-grade"],
            ),
            (
                "student",
                student_auth,
                "Can you plan my next few weeks?",
                ["this week", "next", "focus"],
            ),
            (
                "counsellor",
                counsellor_auth,
                "How many of my students have I grade risk?",
                ["your current counsellor scope", "i-grade"],
            ),
            (
                "counsellor",
                counsellor_auth,
                "How many of my students have R grade risk?",
                ["your current counsellor scope", "r-grade"],
            ),
            (
                "counsellor",
                counsellor_auth,
                "Which of my students need weekly monitoring because of unresolved R grade burden?",
                ["weekly", "unresolved", "r-grade"],
            ),
            (
                "counsellor",
                counsellor_auth,
                "Which students need attention first this week?",
                ["priority", "student_id"],
            ),
            (
                "admin",
                admin_auth,
                "How many students have I grade risk?",
                ["i-grade", "institution"],
            ),
            (
                "admin",
                admin_auth,
                "How many students have R grade risk?",
                ["r-grade", "institution"],
            ),
            (
                "admin",
                admin_auth,
                "Which branch needs attention first?",
                ["branch", "attention"],
            ),
            (
                "admin",
                admin_auth,
                "Which subjects are causing the most attendance issues?",
                ["subject", "attendance"],
            ),
            (
                "admin",
                admin_auth,
                "Show prediction high risk and attendance risk branch wise, year wise and semester wise.",
                ["branch-wise breakdown", "year-wise breakdown", "semester-wise breakdown"],
            ),
        ]

        for role_label, auth, prompt, expected_fragments in cases:
            started_at = datetime.now()
            _log(f"[sweep] start role={role_label} prompt={prompt}")
            answer = _run_prompt(repository=repository, auth=auth, prompt=prompt)
            elapsed = (datetime.now() - started_at).total_seconds()
            lowered = answer.lower()
            _log(f"[sweep] done role={role_label} elapsed={elapsed:.2f}s")
            _log(f"--- {role_label}: {prompt} ---")
            _log(answer)
            for fragment in expected_fragments:
                assert fragment.lower() in lowered, f"Missing fragment `{fragment}` for prompt: {prompt}"

        _log("Live chatbot prompt sweep passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
