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

        cases = [
            (
                "admin",
                "where is the trouble worst right now and why",
                "which branch needs attention first and why",
            ),
            (
                "admin",
                "where is support coverage slipping worst across regions",
                "which region has the highest warning-to-intervention gap",
            ),
            (
                "admin",
                "what subject is hurting us the most attendance wise",
                "which subjects are causing the most attendance issues",
            ),
            (
                "counsellor",
                "who do i need to keep the closest eye on this week",
                "which students need attention first this week",
            ),
            (
                "counsellor",
                "even if they look okay now, who still needs weekly monitoring",
                "which of my students need weekly monitoring because of unresolved r grade burden",
            ),
            (
                "student",
                "attendance looks okay so why am i still red flagged",
                "am i safe or should i worry",
            ),
            (
                "student",
                "what's dragging me down the most and what do i fix first",
                "what exactly is hurting me most and what should i do first",
            ),
            (
                "student",
                "am i still carrying any old grade baggage from older sems",
                "do i still have any uncleared grade issue from older sems",
            ),
        ]

        for role, prompt, expected_rewrite in cases:
            plan, metadata = semantic.plan_copilot_query_with_semantic_assist(
                role=role,
                message=prompt,
                session_messages=[],
                profiles=[],
            )
            print(f"--- {role}: {prompt} ---")
            print(metadata)
            assert metadata["provider"] == "local_fallback"
            assert metadata["status"] in {"rewritten", "rewrite_rejected"}
            assert metadata["rewritten_message"] == expected_rewrite
            if metadata["status"] == "rewritten":
                assert plan.normalized_message == expected_rewrite

        assert provider_calls["count"] == 0
        print("CB19 broader local prompt sweep passed.")
    finally:
        semantic.CB19_ENABLED = original_enabled
        semantic.CB19_LOCAL_FALLBACK_ENABLED = original_local_enabled
        semantic.CB19_CACHE_ENABLED = original_cache_enabled
        semantic._semantic_planner_available = original_available
        semantic._call_semantic_planner = original_call


if __name__ == "__main__":
    main()
