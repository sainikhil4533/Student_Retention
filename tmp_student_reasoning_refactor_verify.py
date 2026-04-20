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
) -> tuple[str, dict]:
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
    return answer, memory_context


def _assert_not_bad(answer: str, label: str) -> None:
    lowered = answer.lower()
    assert "clarification needed" not in lowered, f"Unexpected clarification for `{label}`"
    assert "i can’t help with that request" not in lowered and "i can't help with that request" not in lowered, (
        f"Unexpected refusal for `{label}`"
    )
    assert "passwords or secrets" not in lowered, f"Unexpected sensitive-response collision for `{label}`"


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

        semester_answer, semester_memory = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="which semester i am in right now",
            session_messages=[],
        )
        print("--- semester position ---")
        print(semester_answer)
        print(semester_memory)
        _assert_not_bad(semester_answer, "semester position")
        assert "semester" in semester_answer.lower()

        assignment_total_answer, assignment_total_memory = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="how many total assignments are needed to submit in this semester till now , and how many did i submit till now?",
            session_messages=[],
        )
        print("--- assignment totals ---")
        print(assignment_total_answer)
        print(assignment_total_memory)
        _assert_not_bad(assignment_total_answer, "assignment totals")
        assert "exact total number of assignments" in assignment_total_answer.lower()
        assert "submission rate" in assignment_total_answer.lower()

        label_session: list[_SessionRow] = []
        for prompt in [
            "how many assignments have i submitted",
            "ok",
            "what should i do now?",
            "yes",
        ]:
            answer, memory_context = _run_turn(
                repository=repository,
                auth=student_auth,
                prompt=prompt,
                session_messages=label_session,
            )
            print(f"--- label chain warmup: {prompt} ---")
            print(answer)
            print(memory_context)
            _assert_not_bad(answer, prompt)
        label_answer, label_memory = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="ok give",
            session_messages=label_session,
        )
        print("--- label reduction follow-up ---")
        print(label_answer)
        print(label_memory)
        _assert_not_bad(label_answer, "label reduction follow-up")
        assert "help remove the high risk label first" in label_answer.lower() or "remove the high risk label first" in label_answer.lower()

        week_session: list[_SessionRow] = []
        week_answer, week_memory = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="can you give me week-by-week plan for recovering",
            session_messages=week_session,
        )
        print("--- multi-week plan ---")
        print(week_answer)
        print(week_memory)
        _assert_not_bad(week_answer, "multi-week plan")
        assert "week 1:" in week_answer.lower() and "week 2:" in week_answer.lower()

        second_week_answer, second_week_memory = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="what should i do for second week",
            session_messages=week_session,
        )
        print("--- second week plan ---")
        print(second_week_answer)
        print(second_week_memory)
        _assert_not_bad(second_week_answer, "second week plan")
        assert "second week" in second_week_answer.lower()

        finance_answer, finance_memory = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="is finance affecting my performance",
            session_messages=[],
        )
        print("--- finance vs performance ---")
        print(finance_answer)
        print(finance_memory)
        _assert_not_bad(finance_answer, "finance vs performance")
        assert "finance is affecting" in finance_answer.lower()
        assert "coursework quality" in finance_answer.lower() or "academic weakness" in finance_answer.lower()

        panic_answer, panic_memory = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="should i panic",
            session_messages=[],
        )
        print("--- seriousness check ---")
        print(panic_answer)
        print(panic_memory)
        _assert_not_bad(panic_answer, "should i panic")
        assert "panic is not the right response" in panic_answer.lower()

        print("Student reasoning refactor verification passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
