from __future__ import annotations

from tmp_admin_fixture_family_verify import FixtureAdminClient


def _assert_not_brittle(answer: str, memory: dict, prompt: str) -> None:
    lowered_answer = answer.lower()
    intent = str(memory.get("intent") or "")
    assert intent not in {"planner_clarification", "unsupported"}, f"{prompt!r} fell into {intent!r}"
    assert "i didn" not in lowered_answer, f"{prompt!r} fell into unsupported fallback"
    assert "need one more detail" not in lowered_answer, f"{prompt!r} asked for unnecessary clarification"


def main() -> None:
    health_client = FixtureAdminClient()
    answer, memory = health_client.send("should we be worried")
    _assert_not_brittle(answer, memory, "should we be worried")
    assert "worry" in answer.lower() or "attention" in answer.lower() or "pressure" in answer.lower()

    answer, memory = health_client.send("which factor affects most students")
    _assert_not_brittle(answer, memory, "which factor affects most students")
    assert "factor" in answer.lower() or "driver" in answer.lower() or "academic-performance" in answer.lower()

    grouped_reset_client = FixtureAdminClient()
    answer, memory = grouped_reset_client.send("what strategy should we follow")
    _assert_not_brittle(answer, memory, "what strategy should we follow")
    answer, memory = grouped_reset_client.send("branch wise risk")
    _assert_not_brittle(answer, memory, "branch wise risk")
    assert "branch-wise breakdown" in answer.lower()

    answer, memory = grouped_reset_client.send("only CSE")
    _assert_not_brittle(answer, memory, "only CSE")
    assert "matching students" in answer.lower() or "cse" in answer.lower()

    answer, memory = grouped_reset_client.send("compare with ECE")
    _assert_not_brittle(answer, memory, "compare with ECE")
    assert "comparison" in answer.lower() or "cse" in answer.lower()

    answer, memory = grouped_reset_client.send("why is CSE worse")
    _assert_not_brittle(answer, memory, "why is CSE worse")
    assert "pressure" in answer.lower() or "factor" in answer.lower() or "risk" in answer.lower()

    answer, memory = grouped_reset_client.send("give strategic plan")
    _assert_not_brittle(answer, memory, "give strategic plan")
    assert "plan" in answer.lower() or "action" in answer.lower() or "strategy" in answer.lower()

    comparison_client = FixtureAdminClient()
    answer, memory = comparison_client.send("compare attendance and risk across branches")
    _assert_not_brittle(answer, memory, "compare attendance and risk across branches")
    assert "branch" in answer.lower() or "compare" in answer.lower() or "risk" in answer.lower()

    answer, memory = comparison_client.send("where should we focus")
    _assert_not_brittle(answer, memory, "where should we focus")
    assert "focus" in answer.lower() or "action" in answer.lower() or "priority" in answer.lower()

    print("Admin reasoning refactor verification passed.")


if __name__ == "__main__":
    main()
