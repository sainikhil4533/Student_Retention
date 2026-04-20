from __future__ import annotations

import src.api.copilot_semantic_planner as semantic


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
            raise AssertionError("External semantic provider should not have been called for local-fallback-covered prompts.")

        semantic._call_semantic_planner = _unexpected_provider_call

        admin_plan, admin_meta = semantic.plan_copilot_query_with_semantic_assist(
            role="admin",
            message="who's under the heaviest strain right now and why",
            session_messages=[],
            profiles=[],
        )
        print("--- admin local fallback ---")
        print(admin_meta)
        assert admin_meta["provider"] == "local_fallback"
        assert admin_meta["status"] == "rewritten"
        assert admin_plan.user_goal == "attention_analysis"

        student_plan, student_meta = semantic.plan_copilot_query_with_semantic_assist(
            role="student",
            message="my current attendance is in SAFE mode right but why i have been put into HIGH alert?",
            session_messages=[],
            profiles=[],
        )
        print("--- student local fallback ---")
        print(student_meta)
        assert student_meta["provider"] == "local_fallback"
        assert student_meta["status"] == "rewritten"
        assert student_plan.primary_intent == "student_self_subject_risk"

        clarify_plan, clarify_meta = semantic.plan_copilot_query_with_semantic_assist(
            role="admin",
            message="compare CSE and ECE students in Urban and Rural but what's driving it",
            session_messages=[],
            profiles=[],
        )
        print("--- local clarification fallback ---")
        print(clarify_meta)
        assert clarify_meta["provider"] == "local_fallback"
        assert clarify_meta["status"] == "clarification"
        assert clarify_plan.clarification_needed is True

        assert provider_calls["count"] == 0
        print("CB19 local fallback verification passed.")
    finally:
        semantic.CB19_ENABLED = original_enabled
        semantic.CB19_LOCAL_FALLBACK_ENABLED = original_local_enabled
        semantic.CB19_CACHE_ENABLED = original_cache_enabled
        semantic._semantic_planner_available = original_available
        semantic._call_semantic_planner = original_call


if __name__ == "__main__":
    main()
