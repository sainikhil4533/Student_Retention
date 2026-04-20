from __future__ import annotations

from tmp_counsellor_fixture_conversation_verify import FixtureConversationClient


def _assert_contains(answer: str, expected_any: tuple[str, ...], prompt: str) -> None:
    lowered = answer.lower()
    if not any(fragment in lowered for fragment in expected_any):
        raise AssertionError(f"Prompt `{prompt}` did not match expected fragments {expected_any!r}. Answer: {answer}")


def _run_chain(client: FixtureConversationClient, steps: list[tuple[str, tuple[str, ...]]]) -> None:
    for prompt, expected in steps:
        answer, _memory = client.send(prompt)
        _assert_contains(answer, expected, prompt)


def main() -> None:
    identify_chain = FixtureConversationClient()
    _run_chain(
        identify_chain,
        [
            ("which students are high risk", ("high-risk cohort", "current high-risk student view", "risky-student list")),
            ("ok", ("action list", "support plan", "intervention plan", "risk-reduction plan")),
            ("show top 3", ("top 3", "top-risk view", "student_id")),
            ("why are they high risk", ("grounded explanation", "pressure", "main issue")),
            ("what is common issue", ("main issue", "main pattern", "compounding")),
            ("what should I do first", ("action list", "support plan", "intervention plan")),
            ("which student is most critical", ("most critical", "student_id", "top current risk-priority")),
            ("what happens if I delay", ("if you delay", "delay", "pressure", "harder")),
            ("how fast should I act", ("this week", "fast", "act", "queue")),
            ("give me action plan", ("action list", "support plan", "intervention plan")),
            ("continue", ("action", "plan", "follow-up", "next")),
        ],
    )

    cross_feature_chain = FixtureConversationClient()
    _run_chain(
        cross_feature_chain,
        [
            ("which students have good attendance but high risk", ("safe-looking attendance", "hidden-risk", "model high risk")),
            ("ok", ("action list", "support plan", "intervention plan", "risk-reduction plan")),
            ("why is that happening", ("pressure", "non-attendance", "broader")),
            ("what is main factor", ("main issue", "main pattern", "pressure")),
            ("how can I fix it", ("action list", "support plan", "intervention plan", "risk-reduction plan")),
            ("which students are worst", ("student_id", "performing worst", "most critical", "top current risk-priority")),
            ("what should I do for them", ("action list", "support plan", "intervention plan", "risk-reduction plan")),
            ("how urgent is it", ("serious", "urgent", "queue", "pressure")),
            ("what if no action is taken", ("if no action", "harder", "persist", "pressure")),
            ("give solution plan", ("action list", "support plan", "intervention plan", "risk-reduction plan")),
        ],
    )

    ambiguous_chain = FixtureConversationClient()
    _run_chain(
        ambiguous_chain,
        [
            ("students", ("assigned to your counsellor scope", "student_id", "imported students")),
            ("ok", ("action list", "support plan", "intervention plan", "risk-reduction plan")),
            ("continue", ("action", "plan", "follow-up", "next")),
            ("who", ("student_id", "matching students", "top-risk view", "high-risk cohort")),
            ("why", ("grounded explanation", "pressure", "main issue")),
            ("then", ("action", "plan", "follow-up", "next")),
            ("what next", ("action", "plan", "follow-up", "next")),
            ("ok", ("action", "plan", "follow-up", "next")),
            ("continue", ("action", "plan", "follow-up", "next")),
            ("more", ("action", "plan", "follow-up", "next")),
        ],
    )

    priority_chain = FixtureConversationClient()
    _run_chain(
        priority_chain,
        [
            ("who needs attention", ("high-risk cohort", "student_id", "current high-risk student view")),
            ("ok", ("action list", "support plan", "intervention plan", "risk-reduction plan")),
            ("who is most critical", ("most critical", "student_id", "top current risk-priority")),
            ("why", ("grounded explanation", "pressure", "main issue")),
            ("what should I do first", ("action list", "support plan", "intervention plan", "risk-reduction plan")),
            ("how to prioritize students", ("action list", "priority", "queue", "support plan")),
            ("what if I ignore low risk", ("if", "risk", "pressure", "monitor")),
            ("is that okay", ("okay", "not enough", "monitor", "pressure")),
            ("what is best strategy", ("action list", "support plan", "intervention plan", "risk-reduction plan", "action plan")),
            ("give weekly plan", ("weekly", "plan", "monitoring", "action")),
        ],
    )

    edge_chain = FixtureConversationClient()
    _run_chain(
        edge_chain,
        [
            ("who is worst student", ("performing worst", "student_id", "most critical")),
            ("which student will fail", ("fail", "cannot", "pressure", "risk")),
            ("is situation serious", ("serious", "pressure", "grounded explanation")),
            ("should I worry about my group", ("serious", "pressure", "grounded explanation")),
            ("are things getting worse", ("trend caution", "improvement-versus-pressure", "pressure snapshot")),
            ("compare attendance and assignments for risky students", ("compare", "attendance", "assignments", "pressure")),
            ("which factor is affecting most students", ("main issue", "main pattern", "pressure")),
            ("what is biggest issue across my students", ("main issue", "main pattern", "pressure")),
            ("which students are improving vs declining", ("student_id", "matching students", "improving", "declining")),
        ],
    )

    print("Counsellor fixture deep-chain verification passed.")


if __name__ == "__main__":
    main()
