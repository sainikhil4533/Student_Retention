from __future__ import annotations

from tmp_counsellor_fixture_conversation_verify import FixtureConversationClient


def _assert_no_clarification(answer: str, label: str) -> None:
    lowered = answer.lower()
    assert "clarification needed" not in lowered, f"Unexpected clarification for `{label}`"
    assert "could you please clarify" not in lowered, f"Unexpected clarification prompt for `{label}`"


def main() -> None:
    client = FixtureConversationClient()

    answer, memory = client.send("who needs attention")
    print("--- who needs attention ---")
    print(answer)
    print(memory)
    _assert_no_clarification(answer, "who needs attention")
    assert "student_id" in answer.lower() or "priority" in answer.lower()

    answer, memory = client.send("who all are my students")
    print("--- who all are my students ---")
    print(answer)
    print(memory)
    _assert_no_clarification(answer, "who all are my students")
    assert "assigned to your counsellor scope" in answer.lower() or "current assigned-student list" in answer.lower()

    answer, memory = client.send("show only CSE students")
    print("--- show only CSE students ---")
    print(answer)
    print(memory)
    _assert_no_clarification(answer, "show only CSE students")
    assert "cse" in answer.lower() or "matching students" in answer.lower()

    answer, memory = client.send("which factor is affecting most students")
    print("--- which factor is affecting most students ---")
    print(answer)
    print(memory)
    _assert_no_clarification(answer, "which factor is affecting most students")
    assert memory.get("response_type") == "explanation"
    assert "most-common-factor" in answer.lower() or "factor affecting the most students" in answer.lower()

    answer, memory = client.send("should i worry about my group")
    print("--- should i worry about my group ---")
    print(answer)
    print(memory)
    _assert_no_clarification(answer, "should i worry about my group")
    assert memory.get("response_type") == "explanation"
    assert "worry-level view" in answer.lower() or "group-risk seriousness" in answer.lower()

    answer, memory = client.send("compare attendance and assignments for risky students")
    print("--- compare attendance and assignments for risky students ---")
    print(answer)
    print(memory)
    _assert_no_clarification(answer, "compare attendance and assignments for risky students")
    assert "attendance pressure" in answer.lower() and "assignments pressure" in answer.lower()

    answer, memory = client.send("which student will fail")
    print("--- which student will fail ---")
    print(answer)
    print(memory)
    _assert_no_clarification(answer, "which student will fail")
    assert memory.get("response_type") == "explanation"
    assert "failure-risk view" in answer.lower() or "consequence view" in answer.lower()

    chain_client = FixtureConversationClient()
    answer, _ = chain_client.send("which students are high risk")
    _assert_no_clarification(answer, "chain high risk")
    answer, _ = chain_client.send("ok")
    _assert_no_clarification(answer, "chain ok")
    answer, _ = chain_client.send("show only CSE")
    _assert_no_clarification(answer, "chain show only CSE")
    answer, _ = chain_client.send("what about top 5")
    _assert_no_clarification(answer, "chain top 5")
    answer, memory = chain_client.send("which factor is affecting most students")
    print("--- chain factor explanation ---")
    print(answer)
    print(memory)
    _assert_no_clarification(answer, "chain factor explanation")
    assert memory.get("response_type") == "explanation"

    print("Counsellor reasoning refactor verification passed.")


if __name__ == "__main__":
    main()
