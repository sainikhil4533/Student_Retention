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


def _assert_no_clarification(answer: str, label: str) -> None:
    lowered = answer.lower()
    assert "clarification needed" not in lowered, f"Unexpected clarification loop for `{label}`"
    assert "could you please clarify" not in lowered, f"Unexpected clarification prompt for `{label}`"


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

        direct_cases = [
            {
                "label": "attendance default assumption",
                "prompt": "attendance",
                "expected": ["overall attendance", "weakest visible subject"],
                "response_type": "data",
                "topic": "attendance",
            },
            {
                "label": "assignment rate default assumption",
                "prompt": "assignment rate",
                "expected": ["assignment submission rate", "weighted assessment score"],
                "response_type": "data",
                "topic": "coursework",
            },
            {
                "label": "risk default assumption",
                "prompt": "risk",
                "expected": ["latest risk level", "dominant cross-signal explanation"],
                "response_type": "data",
                "topic": "risk",
            },
            {
                "label": "lms direct data request",
                "prompt": "what is my lms activity",
                "expected": ["lms activity", "unique lms resources"],
                "response_type": "data",
                "topic": "lms",
            },
            {
                "label": "erp direct data request",
                "prompt": "what is my erp data",
                "expected": ["erp academic-performance picture", "submission rate"],
                "response_type": "data",
                "topic": "coursework",
            },
            {
                "label": "finance direct data request",
                "prompt": "fee status",
                "expected": ["finance posture", "payment status"],
                "response_type": "data",
                "topic": "finance",
            },
        ]

        for case in direct_cases:
            answer, memory_context, semantic = _run_turn(
                repository=repository,
                auth=student_auth,
                prompt=case["prompt"],
                session_messages=[],
            )
            lowered = answer.lower()
            print(f"--- {case['label']}: {case['prompt']} ---")
            print(answer)
            print(memory_context)
            print(semantic)
            _assert_no_clarification(answer, case["label"])
            for expected in case["expected"]:
                assert expected.lower() in lowered, f"Missing `{expected}` in `{case['label']}`"
            assert memory_context.get("response_type") == case["response_type"], case["label"]
            assert memory_context.get("last_topic") == case["topic"], case["label"]

        explanation_cases = [
            {
                "label": "why high risk explanation",
                "prompt": "why am i high risk",
                "expected_any": [["latest risk level", "latest prediction risk view"], ["dominant cross-signal explanation"]],
            },
            {
                "label": "attendance contradiction explanation",
                "prompt": "attendance is good but why risk",
                "expected_any": [["attendance view", "overall semester status"], ["dominant cross-signal explanation"]],
            },
        ]
        for case in explanation_cases:
            answer, memory_context, _semantic = _run_turn(
                repository=repository,
                auth=student_auth,
                prompt=case["prompt"],
                session_messages=[],
            )
            lowered = answer.lower()
            print(f"--- {case['label']}: {case['prompt']} ---")
            print(answer)
            print(memory_context)
            _assert_no_clarification(answer, case["label"])
            for expected_group in case["expected_any"]:
                assert any(expected.lower() in lowered for expected in expected_group), case["label"]
            assert memory_context.get("response_type") == "explanation", case["label"]

        action_cases = [
            {
                "label": "improve action request",
                "prompt": "how can i improve",
                "expected_any": ["first focus should be", "grounded path", "fastest recovery path"],
            },
            {
                "label": "recover action request",
                "prompt": "how can i recover from high alert",
                "expected_any": ["grounded path to reduce your current high alert posture", "fastest recovery path"],
            },
        ]
        for case in action_cases:
            answer, memory_context, _semantic = _run_turn(
                repository=repository,
                auth=student_auth,
                prompt=case["prompt"],
                session_messages=[],
            )
            lowered = answer.lower()
            print(f"--- {case['label']}: {case['prompt']} ---")
            print(answer)
            print(memory_context)
            _assert_no_clarification(answer, case["label"])
            assert any(fragment.lower() in lowered for fragment in case["expected_any"]), case["label"]
            assert memory_context.get("response_type") == "action", case["label"]

        followup_session: list[_SessionRow] = []
        attendance_answer, attendance_memory, _ = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="attendance",
            session_messages=followup_session,
        )
        territory_answer, territory_memory, territory_semantic = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="yes",
            session_messages=followup_session,
        )
        action_answer, action_memory, action_semantic = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="continue",
            session_messages=followup_session,
        )
        day_plan_answer, day_plan_memory, day_plan_semantic = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="proceed",
            session_messages=followup_session,
        )
        recovery_impact_answer, recovery_impact_memory, recovery_impact_semantic = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="yes",
            session_messages=followup_session,
        )

        print("--- follow-up chain: attendance -> yes -> continue -> proceed -> yes ---")
        print(attendance_answer)
        print(attendance_memory)
        print(territory_answer)
        print(territory_memory)
        print(territory_semantic)
        print(action_answer)
        print(action_memory)
        print(action_semantic)
        print(day_plan_answer)
        print(day_plan_memory)
        print(day_plan_semantic)
        print(recovery_impact_answer)
        print(recovery_impact_memory)
        print(recovery_impact_semantic)

        for label, answer in {
            "attendance first turn": attendance_answer,
            "territory follow-up": territory_answer,
            "action follow-up": action_answer,
            "day plan follow-up": day_plan_answer,
            "recovery impact follow-up": recovery_impact_answer,
        }.items():
            _assert_no_clarification(answer, label)

        assert attendance_memory.get("response_type") == "data"
        assert territory_memory.get("response_type") == "explanation"
        assert action_memory.get("response_type") == "action"
        assert day_plan_memory.get("response_type") == "action"
        assert recovery_impact_memory.get("response_type") == "action"

        assert "overall semester status" in territory_answer.lower() or "end-sem eligibility" in territory_answer.lower()
        assert "first focus should be" in action_answer.lower() or "grounded path" in action_answer.lower()
        assert "day 1:" in day_plan_answer.lower() and "day 2:" in day_plan_answer.lower()
        assert "grounded path to reduce your current high alert posture" in recovery_impact_answer.lower() or "fastest recovery path" in recovery_impact_answer.lower()

        ambiguous_followup_session: list[_SessionRow] = []
        first_answer, first_memory, _ = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="assignment rate",
            session_messages=ambiguous_followup_session,
        )
        second_answer, second_memory, second_semantic = _run_turn(
            repository=repository,
            auth=student_auth,
            prompt="ok",
            session_messages=ambiguous_followup_session,
        )
        print("--- coursework follow-up chain: assignment rate -> ok ---")
        print(first_answer)
        print(first_memory)
        print(second_answer)
        print(second_memory)
        print(second_semantic)
        _assert_no_clarification(first_answer, "assignment rate first turn")
        _assert_no_clarification(second_answer, "assignment rate follow-up")
        assert "assignment submission rate" in first_answer.lower()
        assert "coursework pattern" in second_answer.lower() or "affecting your risk" in second_answer.lower()
        assert second_memory.get("response_type") == "explanation"

        print("Student pass 1 verification passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
