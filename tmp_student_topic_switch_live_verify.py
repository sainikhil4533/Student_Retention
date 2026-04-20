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
    query_plan, semantic_planner = plan_copilot_query_with_semantic_assist(
        role=auth.role,
        message=prompt,
        session_messages=session_messages,
        profiles=[],
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

        session: list[_SessionRow] = []
        risk_answer, _risk_memory, _risk_semantic = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="am i falling into risk zone or not",
            session_messages=session,
        )
        erp_answer, erp_memory, _erp_semantic = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="what is my erp details",
            session_messages=session,
        )
        finance_answer, finance_memory, _finance_semantic = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="what is my finance details",
            session_messages=session,
        )
        finance_followup_answer, finance_followup_memory, finance_followup_semantic = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="ok",
            session_messages=session,
        )

        print("--- risk answer ---")
        print(risk_answer)
        print("--- erp answer ---")
        print(erp_answer)
        print(erp_memory)
        print("--- finance answer ---")
        print(finance_answer)
        print(finance_memory)
        print("--- finance follow-up answer ---")
        print(finance_followup_answer)
        print(finance_followup_memory)
        print(finance_followup_semantic)

        risk_lowered = risk_answer.lower()
        assert "latest risk level" in risk_lowered

        erp_lowered = erp_answer.lower()
        assert "clarification needed" not in erp_lowered
        assert "erp academic-performance picture" in erp_lowered
        assert "submission rate" in erp_lowered
        assert "weighted assessment score" in erp_lowered
        assert "latest risk level is high" not in erp_lowered
        assert erp_memory.get("pending_student_follow_up") == "coursework_risk_explanation"

        finance_lowered = finance_answer.lower()
        assert "clarification needed" not in finance_lowered
        assert "finance posture" in finance_lowered
        assert "payment status" in finance_lowered
        assert "overdue amount" in finance_lowered
        assert "latest risk level is high" not in finance_lowered
        assert finance_memory.get("pending_student_follow_up") == "finance_risk_explanation"

        finance_followup_lowered = finance_followup_answer.lower()
        assert "clarification needed" not in finance_followup_lowered
        assert "finance posture" in finance_followup_lowered
        assert "risk" in finance_followup_lowered
        assert finance_followup_memory.get("pending_student_follow_up") == "student_action_list"
        assert finance_followup_semantic["provider"] in {"local_fallback", "gemini"} or finance_followup_semantic["status"] == "not_needed"

        print("Student topic-switch live verification passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
