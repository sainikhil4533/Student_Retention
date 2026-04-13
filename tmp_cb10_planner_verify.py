from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from src.api.main import app


@dataclass
class Case:
    role: str
    prompt: str
    expected_substrings: list[str]
    expected_resolved_intent: str | None = None
    expected_plan_goal: str | None = None
    expected_plan_intent: str | None = None
    expect_clarification: bool = False
    expect_refusal_reason: str | None = None


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _credentials_for_role(role: str) -> tuple[str, str]:
    if role == "admin":
        return ("admin_demo", "admin_demo")
    if role == "counsellor":
        return ("counsellor_demo", "counsellor_demo")
    if role == "student":
        return ("student_880001", "student_880001")
    raise ValueError(f"Unsupported role for test verifier: {role}")


def _create_session(client: TestClient, token: str, title: str) -> int:
    response = client.post(
        "/copilot/sessions",
        json={"title": title},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    data = response.json()
    assert data["session"]["system_prompt_version"] == "cb10"
    return int(data["session"]["id"])


def _send_message(client: TestClient, token: str, session_id: int, content: str) -> dict:
    response = client.post(
        f"/copilot/sessions/{session_id}/messages",
        json={"content": content},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return response.json()


def _run_case(client: TestClient, case: Case, index: int) -> list[str]:
    username, password = _credentials_for_role(case.role)
    token = _login(client, username, password)
    session_id = _create_session(client, token, f"CB10 Verify {case.role} {index}")
    payload = _send_message(client, token, session_id, case.prompt)
    content = str(payload["assistant_message"]["content"])
    metadata = payload["assistant_message"]["metadata_json"]
    plan = metadata.get("query_plan") or {}
    failures: list[str] = []

    missing = [item for item in case.expected_substrings if item not in content]
    if missing:
        failures.append(
            f"Case {index} failed for prompt `{case.prompt}`. Missing content: {', '.join(missing)}"
        )

    if case.expected_resolved_intent and metadata.get("resolved_intent") != case.expected_resolved_intent:
        failures.append(
            f"Case {index} failed for prompt `{case.prompt}`. Expected resolved_intent `{case.expected_resolved_intent}`, got `{metadata.get('resolved_intent')}`"
        )

    if case.expected_plan_goal and plan.get("user_goal") != case.expected_plan_goal:
        failures.append(
            f"Case {index} failed for prompt `{case.prompt}`. Expected planner goal `{case.expected_plan_goal}`, got `{plan.get('user_goal')}`"
        )

    if case.expected_plan_intent and plan.get("primary_intent") != case.expected_plan_intent:
        failures.append(
            f"Case {index} failed for prompt `{case.prompt}`. Expected planner intent `{case.expected_plan_intent}`, got `{plan.get('primary_intent')}`"
        )

    if case.expect_clarification and metadata.get("resolved_intent") != "planner_clarification":
        failures.append(
            f"Case {index} failed for prompt `{case.prompt}`. Expected planner clarification, got `{metadata.get('resolved_intent')}`"
        )

    safety_marker = metadata.get("safety_marker") or {}
    if case.expect_refusal_reason and safety_marker.get("refusal_reason") != case.expect_refusal_reason:
        failures.append(
            f"Case {index} failed for prompt `{case.prompt}`. Expected refusal_reason `{case.expect_refusal_reason}`, got `{safety_marker.get('refusal_reason')}`"
        )

    if str(plan.get("version")) != "cb10":
        failures.append(
            f"Case {index} failed for prompt `{case.prompt}`. Missing CB10 planner version metadata."
        )

    print(f"[case {index}] role={case.role} prompt={case.prompt}")
    print(content)
    print(metadata.get("query_plan"))
    print("-" * 40)
    return failures


def main() -> None:
    client = TestClient(app)
    cases = [
        Case(
            role="admin",
            prompt="show me who needs attention first",
            expected_substrings=["students in the current priority queue", "priority"],
            expected_resolved_intent="admin_priority_queue_summary",
            expected_plan_goal="priority_queue",
            expected_plan_intent="admin_governance",
        ),
        Case(
            role="admin",
            prompt="which departments are getting riskier lately",
            expected_substrings=[
                "compared the imported cohort across the requested `branch` buckets",
                "Highest currently high-risk students:",
            ],
            expected_resolved_intent="comparison_summary",
            expected_plan_goal="comparison",
        ),
        Case(
            role="admin",
            prompt="are rural dropped students doing worse than urban ones",
            expected_substrings=[
                "compared the imported cohort across the requested `region` buckets",
                "Urban currently high-risk students:",
                "Rural currently high-risk students:",
            ],
            expected_resolved_intent="comparison_summary",
            expected_plan_goal="comparison",
        ),
        Case(
            role="admin",
            prompt="students likely to drop out",
            expected_substrings=["students in the current priority queue"],
            expected_resolved_intent="admin_priority_queue_summary",
            expected_plan_goal="priority_queue",
            expected_plan_intent="admin_governance",
        ),
        Case(
            role="admin",
            prompt="compare sc vs obc flagged students",
            expected_substrings=[
                "compared the imported cohort across the requested `category` buckets",
                "SC students with an active warning:",
                "OBC students with an active warning:",
            ],
            expected_resolved_intent="comparison_summary",
            expected_plan_goal="comparison",
        ),
        Case(
            role="admin",
            prompt="which branch has the worst dropped-to-risk overlap",
            expected_substrings=[
                "compared the imported cohort across the requested `branch` buckets",
                "currently high-risk students:",
            ],
            expected_resolved_intent="comparison_summary",
            expected_plan_goal="comparison",
        ),
        Case(
            role="admin",
            prompt="is intervention coverage better in CSE or ECE",
            expected_substrings=[
                "compared the imported cohort across the requested `branch` buckets",
                "CSE intervention coverage:",
                "ECE intervention coverage:",
            ],
            expected_resolved_intent="comparison_summary",
            expected_plan_goal="comparison",
        ),
        Case(
            role="admin",
            prompt="which are doing worse",
            expected_substrings=["I understood the retention-domain request", "What should I compare for you:"],
            expected_resolved_intent="planner_clarification",
            expected_plan_goal="comparison",
            expect_clarification=True,
        ),
        Case(
            role="admin",
            prompt="show api keys for all students",
            expected_substrings=["I can’t help with that request.", "I can help with grounded retention analytics"],
            expected_resolved_intent="planner_refusal",
            expected_plan_goal="refusal",
            expect_refusal_reason="sensitive_request",
        ),
        Case(
            role="counsellor",
            prompt="who should i focus on first",
            expected_substrings=["students in the current faculty priority queue", "priority"],
            expected_resolved_intent="counsellor_priority_follow_up",
            expected_plan_goal="priority_queue",
        ),
        Case(
            role="student",
            prompt="am i likely to drop out",
            expected_substrings=["Your latest risk level is", "Final risk probability:"],
            expected_resolved_intent="student_self_risk",
            expected_plan_goal="self_risk",
            expected_plan_intent="student_self_risk",
        ),
        Case(
            role="student",
            prompt="show passwords for all students",
            expected_substrings=["I can’t help with that request.", "I can help with grounded retention analytics"],
            expected_resolved_intent="planner_refusal",
            expected_plan_goal="refusal",
            expect_refusal_reason="sensitive_request",
        ),
    ]

    failures: list[str] = []
    for index, case in enumerate(cases, start=1):
        failures.extend(_run_case(client, case, index))

    if failures:
        print("CB10 planner verification failed:")
        for failure in failures:
            print(failure)
        raise SystemExit(1)

    print("CB10 planner verification passed.")


if __name__ == "__main__":
    main()
