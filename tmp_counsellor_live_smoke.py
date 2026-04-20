from datetime import datetime
import sys
from types import SimpleNamespace

from src.api.auth import AuthContext
from src.api.copilot_memory import resolve_copilot_memory_context
from src.api.copilot_tools import generate_grounded_copilot_answer
from src.api.routes.cases import get_active_cases
from src.api.routes.faculty import get_faculty_dashboard_summary
from src.api.routes.faculty import get_faculty_priority_queue
from src.db.database import SessionLocal
from src.db.repository import EventRepository


def main() -> None:
    target = str(sys.argv[1] if len(sys.argv) > 1 else "all").strip().lower()
    auth = AuthContext(
        role="counsellor",
        subject="counsellor_asha_demo",
        display_name="Counsellor Asha",
        auth_provider="local_smoke",
    )
    db = SessionLocal()
    try:
        if target in {"all", "summary"}:
            started_at = datetime.now()
            summary = get_faculty_dashboard_summary(db=db, auth=auth)
            print("dashboard_summary_ok", summary.total_active_high_risk_students, summary.total_students_with_active_academic_burden, "seconds", (datetime.now() - started_at).total_seconds())

        if target in {"all", "queue"}:
            started_at = datetime.now()
            queue = get_faculty_priority_queue(db=db, auth=auth)
            print(
                "priority_queue_ok",
                queue.total_students,
                "seconds",
                (datetime.now() - started_at).total_seconds(),
            )
            print(
                [
                    (item.student_id, item.priority_label, item.current_risk_level, item.active_burden_count)
                    for item in queue.queue[:8]
                ]
            )

        if target in {"all", "cases"}:
            started_at = datetime.now()
            active_cases = get_active_cases(db=db, auth=auth)
            print(
                "active_cases_ok",
                active_cases.total_students,
                "seconds",
                (datetime.now() - started_at).total_seconds(),
            )
            print(
                [
                    (item.student_id, item.current_case_state, item.priority_label, item.risk_level)
                    for item in active_cases.cases[:12]
                ]
            )

        repository = EventRepository(db)
        session_messages: list[object] = []

        if target in {"all", "assigned"}:
            started_at = datetime.now()
            first_answer, _, _, _ = generate_grounded_copilot_answer(
                auth=auth,
                repository=repository,
                message="who all are my students",
                session_messages=session_messages,
                memory=resolve_copilot_memory_context(message="who all are my students", session_messages=session_messages),
            )
            print("assigned_students_ok", "currently assigned" in first_answer.lower() or "students currently assigned" in first_answer.lower(), "seconds", (datetime.now() - started_at).total_seconds())
            print(first_answer)

        if target in {"all", "followup"}:
            session_messages.extend(
                [
                    SimpleNamespace(role="user", content="who should i focus on first"),
                    SimpleNamespace(
                        role="assistant",
                        content="placeholder",
                        metadata_json={
                            "memory_context": {
                                "kind": "cohort",
                                "pending_role_follow_up": "operational_actions",
                                "last_topic": "high_risk_students",
                                "last_intent": "counsellor_priority_follow_up",
                                "intent": "counsellor_priority_follow_up",
                                "student_ids": [880004, 880005, 880002, 880006, 880001],
                                "role_scope": "counsellor",
                            }
                        },
                    ),
                ]
            )
            started_at = datetime.now()
            followup_answer, _, _, _ = generate_grounded_copilot_answer(
                auth=auth,
                repository=repository,
                message="yes",
                session_messages=session_messages,
                memory=resolve_copilot_memory_context(message="yes", session_messages=session_messages),
            )
            print("followup_ok", "action plan" in followup_answer.lower() or "support plan" in followup_answer.lower() or "operational action" in followup_answer.lower(), "seconds", (datetime.now() - started_at).total_seconds())
            print(followup_answer)
    finally:
        db.close()


if __name__ == "__main__":
    main()
