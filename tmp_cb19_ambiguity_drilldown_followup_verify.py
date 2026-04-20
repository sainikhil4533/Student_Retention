from __future__ import annotations

from dataclasses import dataclass

import src.api.copilot_semantic_planner as semantic


@dataclass
class _SessionRow:
    role: str
    metadata_json: dict


def _assistant_row(memory_context: dict) -> _SessionRow:
    return _SessionRow(role="assistant", metadata_json={"memory_context": memory_context})


def main() -> None:
    original_enabled = semantic.CB19_ENABLED
    original_local_enabled = semantic.CB19_LOCAL_FALLBACK_ENABLED
    original_cache_enabled = semantic.CB19_CACHE_ENABLED
    original_available = semantic._semantic_planner_available
    original_call = semantic._call_semantic_planner

    provider_calls = {"count": 0}

    try:
        semantic.CB19_ENABLED = True
        semantic.CB19_LOCAL_FALLBACK_ENABLED = True
        semantic.CB19_CACHE_ENABLED = False
        semantic._semantic_planner_available = lambda: True

        def _unexpected_provider_call(*args, **kwargs):
            provider_calls["count"] += 1
            raise AssertionError("External semantic provider should not have been called for ambiguity/drilldown follow-up normalization.")

        semantic._call_semantic_planner = _unexpected_provider_call

        cases = [
            (
                "student ambiguity follow-up",
                "student",
                "prediction or attendance?",
                [_assistant_row({"kind": "student_academic", "intent": "risk_layer_difference"})],
                "what is the difference between prediction risk and attendance risk",
            ),
            (
                "admin grouped ambiguity follow-up",
                "admin",
                "what do you mean by that?",
                [_assistant_row({"kind": "import_coverage", "intent": "grouped_risk_breakdown", "grouped_by": "semester"})],
                "what is the difference between prediction risk and attendance risk",
            ),
            (
                "student why-follow-up after safety answer",
                "student",
                "and why exactly?",
                [_assistant_row({"kind": "student_self", "student_id": 1, "intent": "student_self_risk"})],
                "am i safe or should i worry",
            ),
            (
                "admin drilldown why-follow-up",
                "admin",
                "and why exactly?",
                [_assistant_row({"kind": "student_drilldown", "student_id": 880001, "intent": "student_drilldown"})],
                "show details for student 880001",
            ),
        ]

        for label, role, prompt, session_messages, expected_rewrite in cases:
            plan, metadata = semantic.plan_copilot_query_with_semantic_assist(
                role=role,
                message=prompt,
                session_messages=session_messages,
                profiles=[],
            )
            print(f"--- {label}: {prompt} ---")
            print(metadata)
            assert metadata["provider"] == "local_fallback"
            assert metadata["status"] == "rewritten"
            assert metadata["rewritten_message"] == expected_rewrite
            assert plan.normalized_message == expected_rewrite

        assert provider_calls["count"] == 0
        print("CB19 local ambiguity and drilldown follow-up verification passed.")
    finally:
        semantic.CB19_ENABLED = original_enabled
        semantic.CB19_LOCAL_FALLBACK_ENABLED = original_local_enabled
        semantic.CB19_CACHE_ENABLED = original_cache_enabled
        semantic._semantic_planner_available = original_available
        semantic._call_semantic_planner = original_call


if __name__ == "__main__":
    main()
