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
) -> tuple[str, dict, dict]:
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
    finally:
        db.close()
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
    admin_auth = AuthContext(
        role="admin",
        subject="admin.retention",
        display_name="Retention Admin",
        auth_provider="local_institution_account",
    )

    one_turn_cases = [
        (
            "high risk count",
            "how many students are high risk",
            ["currently high-risk students"],
        ),
        (
            "stats default",
            "stats",
            ["currently high-risk students"],
        ),
        (
            "trend default",
            "trend",
            ["newly entered high risk", "last 30 days"],
        ),
        (
            "institution strategy",
            "what strategy should we take",
            ["institution-level action list"],
        ),
        (
            "grouped branch risk",
            "branch-wise risk",
            ["branch-wise breakdown"],
        ),
        (
            "semester year grouped",
            "show prediction high risk and attendance risk semester wise and year wise",
            ["semester-wise breakdown", "year-wise breakdown"],
        ),
        (
            "institution hotspot",
            "which subjects are causing the most attendance issues",
            ["causing the most attendance issues"],
        ),
    ]

    for label, prompt, expected_fragments in one_turn_cases:
        answer, memory_context, semantic = _run_turn(
            auth=admin_auth,
            prompt=prompt,
            session_messages=[],
        )
        lowered = answer.lower()
        print(f"--- {label}: {prompt} ---")
        print(answer)
        print(memory_context)
        print(semantic)
        assert "clarification needed" not in lowered, f"Unexpected clarification for {label}"
        for fragment in expected_fragments:
            assert fragment.lower() in lowered, f"Missing fragment `{fragment}` for `{label}`"

    grouped_session: list[_SessionRow] = []
    grouped_answer, grouped_memory, _ = _run_turn(
        auth=admin_auth,
        prompt="branch-wise risk",
        session_messages=grouped_session,
    )
    only_cse_answer, only_cse_memory, only_cse_semantic = _run_turn(
        auth=admin_auth,
        prompt="only CSE",
        session_messages=grouped_session,
    )
    continue_answer, continue_memory, continue_semantic = _run_turn(
        auth=admin_auth,
        prompt="continue",
        session_messages=grouped_session,
    )
    print("--- admin grouped branch turn ---")
    print(grouped_answer)
    print(grouped_memory)
    print("--- admin only CSE follow-up ---")
    print(only_cse_answer)
    print(only_cse_memory)
    print(only_cse_semantic)
    print("--- admin continue follow-up ---")
    print(continue_answer)
    print(continue_memory)
    print(continue_semantic)
    assert "branch-wise breakdown" in grouped_answer.lower()
    assert "matching students" in only_cse_answer.lower()
    assert "institution-level action list" in continue_answer.lower()

    print("Admin role hardening verification passed.")


if __name__ == "__main__":
    main()
