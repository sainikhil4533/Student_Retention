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
) -> tuple[str, dict, dict]:
    profiles = None
    if auth.role == "admin":
        profiles = repository.get_imported_student_profiles()
    elif auth.role == "counsellor":
        profiles = repository.get_imported_student_profiles_for_counsellor_identity(
            subject=auth.subject,
            display_name=auth.display_name,
        )
    query_plan = plan_copilot_query(
        role=auth.role,
        message=prompt,
        session_messages=session_messages,
        profiles=profiles,
    )
    semantic_planner = {
        "provider": "deterministic_only",
        "status": "not_used",
        "rewritten_message": None,
    }
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

        counsellor_fresh_answer, _, _ = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt="what should i do first for my students",
            session_messages=[],
        )
        print("--- counsellor fresh action ---")
        print(counsellor_fresh_answer)
        lowered = counsellor_fresh_answer.lower()
        assert "operational action list" in lowered
        assert "weekly monitoring" in lowered or "top queue students first" in lowered

        counsellor_grouped_session: list[_SessionRow] = []
        grouped_answer, grouped_memory, grouped_semantic = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt="show my students high risk semester wise",
            session_messages=counsellor_grouped_session,
        )
        continue_answer, _, continue_semantic = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt="continue",
            session_messages=counsellor_grouped_session,
        )
        print("--- counsellor grouped turn 1 ---")
        print(grouped_answer)
        print(grouped_memory)
        print(grouped_semantic)
        print("--- counsellor grouped turn 2 ---")
        print(continue_answer)
        print(continue_semantic)
        assert "semester-wise breakdown" in grouped_answer.lower()
        assert "operational action list" in continue_answer.lower()
        assert "top queue students first" in continue_answer.lower() or "weekly monitoring" in continue_answer.lower()

        admin_fresh_answer, _, _ = _run_turn(
            repository=repository,
            auth=admin_auth,
            prompt="what should we do first institution wide",
            session_messages=[],
        )
        print("--- admin fresh action ---")
        print(admin_fresh_answer)
        lowered = admin_fresh_answer.lower()
        assert "institution-level action list" in lowered
        assert "first operational move" in lowered or "carry-forward governance" in lowered

        admin_attention_session: list[_SessionRow] = []
        attention_answer, _, attention_semantic = _run_turn(
            repository=repository,
            auth=admin_auth,
            prompt="which branch needs attention first and why",
            session_messages=admin_attention_session,
        )
        attention_followup_answer, _, attention_followup_semantic = _run_turn(
            repository=repository,
            auth=admin_auth,
            prompt="ok",
            session_messages=admin_attention_session,
        )
        print("--- admin attention turn 1 ---")
        print(attention_answer)
        print(attention_semantic)
        print("--- admin attention turn 2 ---")
        print(attention_followup_answer)
        print(attention_followup_semantic)
        assert "needs attention first" in attention_answer.lower()
        assert "institution-level action list" in attention_followup_answer.lower()

        print("Role operational advisory verification passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
