from __future__ import annotations

from tmp_admin_fixture_family_verify import FixtureAdminClient


def _assert_chain(client: FixtureAdminClient, prompts: list[str]) -> None:
    for prompt in prompts:
        answer, memory = client.send(prompt)
        lowered_answer = answer.lower()
        intent = str(memory.get("intent") or "")
        assert intent not in {"planner_clarification", "unsupported"}, f"{prompt!r} fell into {intent!r}"
        assert "i didn" not in lowered_answer, f"{prompt!r} fell into unsupported fallback"
        assert "need one more detail" not in lowered_answer, f"{prompt!r} asked for unnecessary clarification"


def main() -> None:
    _assert_chain(
        FixtureAdminClient(),
        [
            "branch wise risk",
            "ok",
            "only CSE",
            "compare with ECE",
            "why is CSE worse",
            "what is main factor",
            "what should we fix first",
            "how long will it take to improve",
            "what if we don't act",
            "which branch needs urgent attention",
            "give strategic plan",
        ],
    )
    _assert_chain(
        FixtureAdminClient(),
        [
            "how many students are high risk",
            "ok",
            "break it by branch",
            "which branch has highest risk",
            "why",
            "what is affecting them",
            "what actions should we take",
            "can we reduce risk quickly",
            "how much improvement is possible",
            "give detailed plan",
        ],
    )
    _assert_chain(
        FixtureAdminClient(),
        [
            "stats",
            "ok",
            "continue",
            "risk",
            "why",
            "then",
            "what next",
            "continue",
            "more",
            "explain",
        ],
    )
    _assert_chain(
        FixtureAdminClient(),
        [
            "which branch has good attendance but high risk",
            "ok",
            "why is that happening",
            "what is main cause",
            "how to fix it",
            "which branch is worst affected",
            "how urgent is it",
            "what if we ignore this",
            "can situation get worse",
            "give full solution plan",
        ],
    )
    _assert_chain(
        FixtureAdminClient(),
        [
            "which branch is worst",
            "ok",
            "why",
            "what should we do",
            "how fast should we act",
            "what if no action is taken",
            "what is worst case scenario",
            "can we recover in 1 semester",
            "what is realistic timeline",
            "give strategic roadmap",
        ],
    )
    print("Admin fixture deep-chain verification passed.")


if __name__ == "__main__":
    main()
