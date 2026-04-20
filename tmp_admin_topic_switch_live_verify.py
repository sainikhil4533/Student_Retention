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
    auth: AuthContext,
    prompt: str,
    session_messages: list[_SessionRow],
) -> tuple[str, dict]:
    db = SessionLocal()
    try:
        repository = EventRepository(db)
        profiles = repository.get_imported_student_profiles()
        query_plan = plan_copilot_query(
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
    finally:
        db.close()
    session_messages.append(_SessionRow(role="assistant", metadata_json={"memory_context": memory_context}))
    return answer, memory_context


def main() -> None:
    admin_auth = AuthContext(
        role="admin",
        subject="admin.retention",
        display_name="Retention Admin",
        auth_provider="local_institution_account",
    )

    session: list[_SessionRow] = []
    risk_answer, _risk_memory = _run_turn(
        auth=admin_auth,
        prompt="how many students are high risk",
        session_messages=session,
    )
    trend_answer, trend_memory = _run_turn(
        auth=admin_auth,
        prompt="trend",
        session_messages=session,
    )
    subject_answer, subject_memory = _run_turn(
        auth=admin_auth,
        prompt="which subjects are causing the most attendance issues",
        session_messages=session,
    )
    strategy_answer, strategy_memory = _run_turn(
        auth=admin_auth,
        prompt="what strategy should we take",
        session_messages=session,
    )

    print("--- admin risk answer ---")
    print(risk_answer)
    print("--- admin trend answer ---")
    print(trend_answer)
    print(trend_memory)
    print("--- admin subject answer ---")
    print(subject_answer)
    print(subject_memory)
    print("--- admin strategy answer ---")
    print(strategy_answer)
    print(strategy_memory)

    assert "high-risk cohort" in risk_answer.lower() or "currently high-risk students" in risk_answer.lower()

    trend_lowered = trend_answer.lower()
    assert "clarification needed" not in trend_lowered
    assert "last 30 days" in trend_lowered or "newly entered high risk" in trend_lowered

    subject_lowered = subject_answer.lower()
    assert "clarification needed" not in subject_lowered
    assert "causing the most attendance issues" in subject_lowered or "top attendance hotspot" in subject_lowered

    strategy_lowered = strategy_answer.lower()
    assert "clarification needed" not in strategy_lowered
    assert "institution-level action list" in strategy_lowered or "operational action list" in strategy_lowered
    assert strategy_memory.get("pending_role_follow_up") == "operational_actions"

    print("Admin topic-switch live verification passed.")


if __name__ == "__main__":
    main()
