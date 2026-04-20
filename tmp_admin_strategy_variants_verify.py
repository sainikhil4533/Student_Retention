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


def _run_turn(*, auth: AuthContext, prompt: str, session_messages: list[_SessionRow]) -> tuple[str, dict]:
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

    prompts = [
        "what should we do to reduce risk",
        "how to improve student retention",
        "what strategy should we follow",
        "how can we reduce dropout rate",
        "what actions should admin take",
        "give improvement plan",
    ]

    for prompt in prompts:
        answer, memory_context = _run_turn(auth=admin_auth, prompt=prompt, session_messages=[])
        lowered = answer.lower()
        print(f"--- {prompt} ---")
        print(answer)
        print(memory_context)
        assert "clarification needed" not in lowered
        assert "institution-level action list" in lowered or "action list" in lowered
        assert memory_context.get("response_type") == "action"
        assert memory_context.get("last_topic") == "institution_actions"

    print("Admin strategy variants verification passed.")


if __name__ == "__main__":
    main()
