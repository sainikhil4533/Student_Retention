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

        one_turn_cases = [
            (
                "attendance data",
                "what is my attendance",
                ["overall attendance", "weakest visible subject"],
            ),
            (
                "assignment rate default",
                "how are my assignment rate",
                ["assignment submission rate", "weighted assessment score"],
            ),
            (
                "why high risk explanation",
                "why am i high risk",
                ["latest risk level", "dominant cross-signal explanation"],
            ),
            (
                "how can i improve action",
                "how can i improve",
                ["first focus should be", "targeted support"],
            ),
            (
                "attendance good but why risk",
                "attendance is good but why risk",
                ["attendance view", "dominant cross-signal explanation"],
            ),
        ]

        for label, prompt, expected_fragments in one_turn_cases:
            answer, memory_context, semantic = _run_turn(
                repository=repository,
                auth=student_auth,
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
                assert fragment.lower() in lowered, f"Missing fragment `{fragment}` for case `{label}`"

        followup_session: list[_SessionRow] = []
        first_answer, first_memory, _ = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="why am i high risk",
            session_messages=followup_session,
        )
        second_answer, second_memory, second_semantic = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="ok",
            session_messages=followup_session,
        )
        print("--- student risk follow-up first turn ---")
        print(first_answer)
        print(first_memory)
        print("--- student risk follow-up second turn ---")
        print(second_answer)
        print(second_memory)
        print(second_semantic)
        assert first_memory.get("pending_student_follow_up") == "student_action_list"
        second_lowered = second_answer.lower()
        assert "grounded path" in second_lowered or "fastest recovery path" in second_lowered or "first focus" in second_lowered
        assert "clarification needed" not in second_lowered

        print("Student role hardening verification passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
