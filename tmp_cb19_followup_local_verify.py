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
            raise AssertionError("External semantic provider should not have been called for local follow-up normalization.")

        semantic._call_semantic_planner = _unexpected_provider_call

        cases = [
            (
                "student attendance follow-up",
                "student",
                "ok",
                [_assistant_row({"pending_student_follow_up": "attendance_territory"})],
                "do i have i grade risk or r grade risk and am i eligible for end sem",
            ),
            (
                "student action-list follow-up",
                "student",
                "so what",
                [_assistant_row({"pending_student_follow_up": "student_action_list"})],
                "what should i do first",
            ),
            (
                "student weekly breakdown follow-up",
                "student",
                "then?",
                [_assistant_row({"pending_student_follow_up": "weekly_focus_breakdown"})],
                "break down my next few weeks into attendance, coursework, and recovery focus",
            ),
            (
                "admin grouped dimension extension",
                "admin",
                "branch wise also",
                [_assistant_row({"kind": "admin_academic", "intent": "admin_high_risk_semester_year_breakdown"})],
                "show prediction high risk and attendance risk branch wise",
            ),
            (
                "counsellor grouped dimension extension",
                "counsellor",
                "semester wise also",
                [_assistant_row({"kind": "import_coverage", "grouped_by": "gender", "intent": "grouped_attendance_risk"})],
                "show attendance risk semester wise",
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
        print("CB19 local follow-up normalization verification passed.")
    finally:
        semantic.CB19_ENABLED = original_enabled
        semantic.CB19_LOCAL_FALLBACK_ENABLED = original_local_enabled
        semantic.CB19_CACHE_ENABLED = original_cache_enabled
        semantic._semantic_planner_available = original_available
        semantic._call_semantic_planner = original_call


if __name__ == "__main__":
    main()
