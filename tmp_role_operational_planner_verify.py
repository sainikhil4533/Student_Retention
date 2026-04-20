from __future__ import annotations

from dataclasses import dataclass

from src.api.copilot_planner import plan_copilot_query
from src.api.copilot_semantic_planner import plan_copilot_query_with_semantic_assist


@dataclass
class _SessionRow:
    role: str
    metadata_json: dict


def main() -> None:
    admin_plan = plan_copilot_query(
        role="admin",
        message="what should we do first institution wide",
        session_messages=[],
        profiles=[],
    )
    print("--- admin fresh action plan ---")
    print(admin_plan.to_dict())
    assert admin_plan.user_goal == "role_action_request"
    assert admin_plan.analysis_mode == "operational_advisory"

    counsellor_plan = plan_copilot_query(
        role="counsellor",
        message="what should i do first for my students",
        session_messages=[],
        profiles=[],
    )
    print("--- counsellor fresh action plan ---")
    print(counsellor_plan.to_dict())
    assert counsellor_plan.user_goal == "role_action_request"
    assert counsellor_plan.analysis_mode == "operational_advisory"

    admin_session = [
        _SessionRow(
            role="assistant",
            metadata_json={
                "memory_context": {
                    "kind": "import_coverage",
                    "intent": "grouped_risk_breakdown",
                    "grouped_by": "branch",
                    "bucket_values": ["CSE", "ECE"],
                    "pending_role_follow_up": "operational_actions",
                }
            },
        )
    ]
    _admin_followup_plan, admin_semantic = plan_copilot_query_with_semantic_assist(
        role="admin",
        message="ok",
        session_messages=admin_session,
        profiles=[],
    )
    print("--- admin follow-up semantic ---")
    print(admin_semantic)
    assert admin_semantic["provider"] == "local_fallback"
    assert admin_semantic["rewritten_message"] == "what should we do first institution wide"

    counsellor_session = [
        _SessionRow(
            role="assistant",
            metadata_json={
                "memory_context": {
                    "kind": "import_coverage",
                    "intent": "grouped_risk_breakdown",
                    "grouped_by": "semester",
                    "bucket_values": ["Year 3 Sem 6", "Year 4 Sem 7"],
                    "pending_role_follow_up": "operational_actions",
                }
            },
        )
    ]
    _counsellor_followup_plan, counsellor_semantic = plan_copilot_query_with_semantic_assist(
        role="counsellor",
        message="continue",
        session_messages=counsellor_session,
        profiles=[],
    )
    print("--- counsellor follow-up semantic ---")
    print(counsellor_semantic)
    assert counsellor_semantic["provider"] == "local_fallback"
    assert counsellor_semantic["rewritten_message"] == "what should i do first for my students"

    print("Role operational planner verification passed.")


if __name__ == "__main__":
    main()
