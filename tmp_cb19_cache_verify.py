from __future__ import annotations

from pathlib import Path

import src.api.copilot_semantic_planner as semantic


def main() -> None:
    cache_path = Path(".cache") / "tmp_cb19_cache_verify.json"
    if cache_path.exists():
        cache_path.unlink()

    provider_calls = {"count": 0}

    original_enabled = semantic.CB19_ENABLED
    original_cache_enabled = semantic.CB19_CACHE_ENABLED
    original_local_enabled = semantic.CB19_LOCAL_FALLBACK_ENABLED
    original_cache_path = semantic.CB19_CACHE_PATH
    original_available = semantic._semantic_planner_available
    original_call = semantic._call_semantic_planner

    try:
        semantic.CB19_ENABLED = True
        semantic.CB19_CACHE_ENABLED = True
        semantic.CB19_LOCAL_FALLBACK_ENABLED = False
        semantic.CB19_CACHE_PATH = cache_path
        semantic._semantic_planner_available = lambda: True

        def _fake_call_semantic_planner(*, role, message, base_plan):
            provider_calls["count"] += 1
            return {
                "action": "rewrite",
                "rewritten_message": "show grouped admin risk breakdown",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.93,
                "rationale": "normalized a fuzzy pressure-style prompt into a grounded grouped-risk query",
            }

        semantic._call_semantic_planner = _fake_call_semantic_planner

        first_plan, first_meta = semantic.plan_copilot_query_with_semantic_assist(
            role="admin",
            message="who's under the heaviest strain right now and why",
            session_messages=[],
            profiles=[],
        )
        second_plan, second_meta = semantic.plan_copilot_query_with_semantic_assist(
            role="admin",
            message="who's under the heaviest strain right now and why",
            session_messages=[],
            profiles=[],
        )

        print("--- first metadata ---")
        print(first_meta)
        print("--- second metadata ---")
        print(second_meta)

        assert provider_calls["count"] == 1
        assert first_meta["used"] is True
        assert second_meta["cache_hit"] is True
        assert second_meta["status"] in {"cache_hit", "rewrite_rejected_from_cache", "refusal", "clarification", "kept"}
        assert first_plan.normalized_message or first_plan.user_goal
        assert second_plan.normalized_message or second_plan.user_goal

        print("CB19 semantic cache verification passed.")
    finally:
        semantic.CB19_ENABLED = original_enabled
        semantic.CB19_CACHE_ENABLED = original_cache_enabled
        semantic.CB19_LOCAL_FALLBACK_ENABLED = original_local_enabled
        semantic.CB19_CACHE_PATH = original_cache_path
        semantic._semantic_planner_available = original_available
        semantic._call_semantic_planner = original_call
        if cache_path.exists():
            cache_path.unlink()


if __name__ == "__main__":
    main()
