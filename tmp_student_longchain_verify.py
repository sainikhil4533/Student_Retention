from __future__ import annotations

from dataclasses import dataclass

from src.api.auth import AuthContext
from src.api.copilot_memory import resolve_copilot_memory_context
import src.api.copilot_semantic_planner as semantic_planner_module
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
    original_provider_check = semantic_planner_module._semantic_planner_available
    original_cache_get = semantic_planner_module._get_cached_semantic_hint
    original_cache_store = semantic_planner_module._store_cached_semantic_hint
    semantic_planner_module._semantic_planner_available = lambda: False
    semantic_planner_module._get_cached_semantic_hint = lambda _cache_key: None
    semantic_planner_module._store_cached_semantic_hint = lambda _cache_key, _hint: None
    try:
        query_plan, semantic_planner = plan_copilot_query_with_semantic_assist(
            role=auth.role,
            message=prompt,
            session_messages=session_messages,
            profiles=[],
        )
    finally:
        semantic_planner_module._semantic_planner_available = original_provider_check
        semantic_planner_module._get_cached_semantic_hint = original_cache_get
        semantic_planner_module._store_cached_semantic_hint = original_cache_store
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


def _assert_no_clarification(answer: str, label: str) -> None:
    lowered = answer.lower()
    assert "clarification needed" not in lowered, f"Unexpected clarification loop for `{label}`"
    assert "could you please clarify" not in lowered, f"Unexpected clarification prompt for `{label}`"
    assert "you can reply in a short way and i will continue from there" not in lowered, (
        f"Unexpected clarification tail for `{label}`"
    )


def _assert_contains_any(answer: str, label: str, expected_fragments: list[str]) -> None:
    lowered = answer.lower()
    assert any(fragment.lower() in lowered for fragment in expected_fragments), (
        f"`{label}` did not contain any of the expected grounded fragments: {expected_fragments}"
    )


def _verify_risk_action_consequence_chain(repository: EventRepository, auth: AuthContext) -> None:
    session: list[_SessionRow] = []
    chain = [
        ("why am i high risk", "explanation", ["latest risk level", "dominant cross-signal explanation"]),
        ("ok", "action", ["first focus should be", "grounded path", "fastest recovery path"]),
        ("what should i do", "action", ["first focus should be", "grounded path", "fastest recovery path"]),
        ("continue", "action", ["day 1:", "day by day", "day-by-day"]),
        ("which is most important", "action", ["top priority", "most important", "first focus should be"]),
        ("what happens if i ignore this", "explanation", ["if these drivers do not improve", "current risk drivers", "worst case"]),
        ("how fast can i improve", "explanation", ["recovery", "improve", "time"]),
        ("what if i only fix assignments", "explanation", ["assignments", "not enough", "would help"]),
        ("is that enough", "explanation", ["not enough", "assignments", "other drivers"]),
        ("what else should i do", "action", ["next useful step", "also focus", "first focus should be", "top priority", "second priority"]),
        ("give me a full recovery plan", "action", ["day 1:", "week", "plan"]),
    ]

    previous_answer = ""
    for index, (prompt, expected_type, fragments) in enumerate(chain, start=1):
        answer, memory_context, semantic = _run_turn(
            repository=repository,
            auth=auth,
            prompt=prompt,
            session_messages=session,
        )
        print(f"--- risk/action/consequence turn {index}: {prompt} ---")
        print(answer)
        print(memory_context)
        print(semantic)
        _assert_no_clarification(answer, f"risk chain turn {index}")
        assert memory_context.get("response_type") == expected_type, (
            f"Expected response_type `{expected_type}` on risk chain turn {index}, "
            f"got `{memory_context.get('response_type')}`"
        )
        _assert_contains_any(answer, f"risk chain turn {index}", fragments)
        assert answer.strip() != previous_answer.strip(), f"Repeated answer on risk chain turn {index}"
        previous_answer = answer


def _verify_assignment_followup_chain(repository: EventRepository, auth: AuthContext) -> None:
    session: list[_SessionRow] = []
    chain = [
        ("what is my assignment rate", "data", ["assignment submission rate", "weighted assessment score"]),
        ("ok", "explanation", ["coursework pattern", "affecting your risk", "coursework pressure"]),
        ("is it good or bad", "explanation", ["good or bad", "coursework", "risk"]),
        ("why is it low", "explanation", ["coursework", "submission", "weighted assessment score"]),
        ("how can i improve it", "action", ["first focus should be", "coursework", "assignments"]),
        ("how many assignments should i complete", "action", ["prioritize", "next", "assignments", "coursework-focused priority plan", "submission rate"]),
        ("what if i miss next one", "explanation", ["risk", "coursework", "miss"]),
        ("will my risk increase", "explanation", ["risk", "increase", "coursework"]),
        ("by how much", "explanation", ["cannot promise an exact", "directionally", "risk"]),
        ("what should i prioritize now", "action", ["first focus should be", "prioritize", "next useful step"]),
        ("give me a step by step plan", "action", ["day 1:", "plan", "week"]),
    ]

    previous_answer = ""
    for index, (prompt, expected_type, fragments) in enumerate(chain, start=1):
        answer, memory_context, semantic = _run_turn(
            repository=repository,
            auth=auth,
            prompt=prompt,
            session_messages=session,
        )
        print(f"--- assignment/followup turn {index}: {prompt} ---")
        print(answer)
        print(memory_context)
        print(semantic)
        _assert_no_clarification(answer, f"assignment chain turn {index}")
        assert memory_context.get("response_type") == expected_type, (
            f"Expected response_type `{expected_type}` on assignment chain turn {index}, "
            f"got `{memory_context.get('response_type')}`"
        )
        _assert_contains_any(answer, f"assignment chain turn {index}", fragments)
        assert answer.strip() != previous_answer.strip(), f"Repeated answer on assignment chain turn {index}"
        previous_answer = answer


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

        _verify_risk_action_consequence_chain(repository, student_auth)
        _verify_assignment_followup_chain(repository, student_auth)

        print("Student long-chain verification passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
