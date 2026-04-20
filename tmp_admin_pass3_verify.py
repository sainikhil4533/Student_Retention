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

    one_turn_cases = [
        (
            "stats default",
            "stats",
            ["currently high-risk students"],
            "data",
            "institution_risk",
        ),
        (
            "trend default",
            "trend",
            ["newly entered high risk", "last 30 days"],
            "data",
            "trend",
        ),
        (
            "subject hotspot",
            "which subjects are causing the most attendance issues",
            ["causing the most attendance issues"],
            "explanation",
            "attendance_pressure",
        ),
        (
            "strategy action",
            "what strategy should we take",
            ["institution-level action list"],
            "action",
            "institution_actions",
        ),
    ]

    for label, prompt, expected_fragments, expected_type, expected_topic in one_turn_cases:
        answer, memory_context = _run_turn(auth=admin_auth, prompt=prompt, session_messages=[])
        lowered = answer.lower()
        print(f"--- {label}: {prompt} ---")
        print(answer)
        print(memory_context)
        assert "clarification needed" not in lowered, f"Unexpected clarification for {label}"
        for fragment in expected_fragments:
            assert fragment.lower() in lowered, f"Missing fragment `{fragment}` for `{label}`"
        assert memory_context.get("response_type") == expected_type, f"Unexpected response_type for {label}"
        assert memory_context.get("last_topic") == expected_topic, f"Unexpected last_topic for {label}"

    grouped_session: list[_SessionRow] = []
    grouped_answer, grouped_memory = _run_turn(
        auth=admin_auth,
        prompt="branch-wise risk",
        session_messages=grouped_session,
    )
    filtered_answer, filtered_memory = _run_turn(
        auth=admin_auth,
        prompt="only CSE",
        session_messages=grouped_session,
    )
    continue_answer, continue_memory = _run_turn(
        auth=admin_auth,
        prompt="continue",
        session_messages=grouped_session,
    )
    print("--- admin grouped branch turn ---")
    print(grouped_answer)
    print(grouped_memory)
    print("--- admin grouped filter turn ---")
    print(filtered_answer)
    print(filtered_memory)
    print("--- admin grouped continue turn ---")
    print(continue_answer)
    print(continue_memory)
    assert "branch-wise breakdown" in grouped_answer.lower()
    assert grouped_memory.get("response_type") == "explanation"
    assert grouped_memory.get("last_topic") == "grouped_branch"
    assert "matching students" in filtered_answer.lower()
    assert filtered_memory.get("response_type") == "data"
    assert "institution-level action list" in continue_answer.lower()
    assert continue_memory.get("response_type") == "action"
    assert continue_memory.get("last_topic") == "institution_actions"

    print("Admin pass 3 verification passed.")


if __name__ == "__main__":
    main()
