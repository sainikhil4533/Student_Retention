from __future__ import annotations

from dataclasses import dataclass

from src.api.copilot_memory import resolve_copilot_memory_context
from src.api.copilot_planner import plan_copilot_query


@dataclass
class _SessionRow:
    role: str
    metadata_json: dict


def main() -> None:
    student_plan = plan_copilot_query(
        role="student",
        message="how are my assignment rate",
        session_messages=[],
        profiles=[],
    )
    print("--- student default assumption plan ---")
    print(student_plan.to_dict())
    assert student_plan.normalized_message == "what is my assignment submission rate right now"
    assert student_plan.primary_intent == "student_self_attendance"
    assert student_plan.user_goal == "student_data_request"
    assert not student_plan.clarification_needed

    student_followup_session = [
        _SessionRow(
            role="assistant",
            metadata_json={
                "memory_context": {
                    "kind": "planner",
                    "intent": "planner_clarification",
                    "default_follow_up_rewrite": "what is my assignment submission rate right now",
                }
            },
        )
    ]
    student_followup_plan = plan_copilot_query(
        role="student",
        message="yes",
        session_messages=student_followup_session,
        profiles=[],
    )
    print("--- student clarification continuation plan ---")
    print(student_followup_plan.to_dict())
    assert student_followup_plan.normalized_message == "what is my assignment submission rate right now"
    assert student_followup_plan.primary_intent == "student_self_attendance"

    counsellor_plan = plan_copilot_query(
        role="counsellor",
        message="risk",
        session_messages=[],
        profiles=[],
    )
    print("--- counsellor default assumption plan ---")
    print(counsellor_plan.to_dict())
    assert counsellor_plan.normalized_message == "which students are high risk"
    assert counsellor_plan.primary_intent == "cohort_summary"

    admin_plan = plan_copilot_query(
        role="admin",
        message="risk",
        session_messages=[],
        profiles=[],
    )
    print("--- admin default assumption plan ---")
    print(admin_plan.to_dict())
    assert admin_plan.normalized_message == "how many students are high risk"
    assert admin_plan.primary_intent == "cohort_summary"

    memory = resolve_copilot_memory_context(
        message="ok",
        session_messages=[
            _SessionRow(
                role="assistant",
                metadata_json={"memory_context": {"kind": "student_self", "intent": "student_self_attendance"}},
            )
        ],
    )
    print("--- short continuation memory ---")
    print(memory)
    assert memory["is_follow_up"] is True

    print("Shared core default verification passed.")


if __name__ == "__main__":
    main()
