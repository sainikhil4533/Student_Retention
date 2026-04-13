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
    expected_version: str = "cb22"


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/auth/login", json={"username": username, "password": password})
    response.raise_for_status()
    return response.json()["access_token"]


def _credentials_for_role(role: str) -> tuple[str, str]:
    if role == "admin":
        return ("admin_demo", "admin_demo")
    if role == "counsellor":
        return ("counsellor_demo", "counsellor_demo")
    if role == "student":
        return ("student_880001", "student_880001")
    raise ValueError(f"Unsupported role: {role}")


def _create_session(client: TestClient, token: str, title: str, expected_version: str) -> int:
    response = client.post(
        "/copilot/sessions",
        json={"title": title},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    payload = response.json()
    assert payload["session"]["system_prompt_version"] == expected_version
    return int(payload["session"]["id"])


def _send(client: TestClient, token: str, session_id: int, prompt: str) -> dict:
    response = client.post(
        f"/copilot/sessions/{session_id}/messages",
        json={"content": prompt},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return response.json()


def main() -> None:
    client = TestClient(app)
    cases = [
        Case(
            role="admin",
            prompt="compare dropped students in CSE vs ECE by warnings and counsellor coverage",
            expected_substrings=[
                "compared the imported cohort across the requested `branch` buckets",
                "CSE matching students:",
                "CSE students with an active warning:",
                "CSE counsellor coverage:",
                "ECE matching students:",
                "ECE students with an active warning:",
                "ECE counsellor coverage:",
            ],
            expected_resolved_intent="comparison_summary",
            expected_plan_goal="comparison",
        ),
        Case(
            role="admin",
            prompt="compare Urban vs Rural students and tell me what is driving the gap",
            expected_substrings=[
                "diagnosed the requested `region` buckets",
                "Primary driver:",
                "diagnostic snapshot:",
            ],
            expected_resolved_intent="diagnostic_comparison_summary",
            expected_plan_goal="diagnostic_comparison",
        ),
        Case(
            role="admin",
            prompt="which branch needs attention first and why",
            expected_substrings=[
                "ranked the requested `branch` buckets by current retention attention pressure",
                "needs attention first with an attention index of",
                "Why:",
                "snapshot:",
            ],
            expected_resolved_intent="attention_analysis_summary",
            expected_plan_goal="attention_analysis",
        ),
        Case(
            role="admin",
            prompt="which region is slipping most lately",
            expected_substrings=[
                "ranked the requested `region` buckets by current retention attention pressure",
                "needs attention first with an attention index of",
                "Why:",
            ],
            expected_resolved_intent="attention_analysis_summary",
            expected_plan_goal="attention_analysis",
        ),
        Case(
            role="admin",
            prompt="compare dropped students in CSE vs ECE by warnings and counsellor coverage and tell me who needs attention most",
            expected_substrings=[
                "ranked the requested `branch` buckets by current retention attention pressure",
                "needs attention first with an attention index of",
                "Why:",
            ],
            expected_resolved_intent="attention_analysis_summary",
            expected_plan_goal="attention_analysis",
        ),
        Case(
            role="admin",
            prompt="which branch has the worst dropped-to-risk overlap",
            expected_substrings=[
                "compared the imported cohort across the requested `branch` buckets",
                "dropped-to-risk overlap:",
                "Worst dropped-to-risk overlap:",
            ],
            expected_resolved_intent="comparison_summary",
            expected_plan_goal="comparison",
        ),
        Case(
            role="admin",
            prompt="which departments saw the most students newly enter risk in the last 30 days",
            expected_substrings=[
                "compared the imported cohort across the requested `branch` buckets",
                "newly high-risk students in the last 30 days:",
                "Highest newly high-risk students in the last 30 days:",
            ],
            expected_resolved_intent="comparison_summary",
            expected_plan_goal="comparison",
        ),
        Case(
            role="admin",
            prompt="which region has the highest warning-to-intervention gap",
            expected_substrings=[
                "compared the imported cohort across the requested `region` buckets",
                "warning-to-intervention gap:",
                "Largest warning-to-intervention gap:",
            ],
            expected_resolved_intent="comparison_summary",
            expected_plan_goal="comparison",
        ),
        Case(
            role="admin",
            prompt="which branch has the highest unresolved risk burden",
            expected_substrings=[
                "compared the imported cohort across the requested `branch` buckets",
                "unresolved risk burden:",
                "Highest unresolved risk burden:",
            ],
            expected_resolved_intent="comparison_summary",
            expected_plan_goal="comparison",
        ),
        Case(
            role="admin",
            prompt="which departments are getting riskier lately",
            expected_substrings=[
                "compared recent `branch` trends across the requested imported cohort buckets",
                "newly high-risk students in the last 30 days:",
                "newly high-risk students in the previous 30 days:",
                "risk-entry trend:",
                "Most worsening recent high-risk-entry trend versus the previous window:",
            ],
            expected_resolved_intent="comparison_summary",
            expected_plan_goal="comparison",
        ),
        Case(
            role="admin",
            prompt="which region intervention coverage is improving",
            expected_substrings=[
                "compared recent `region` trends across the requested imported cohort buckets",
                "intervention coverage in the last 30 days:",
                "intervention coverage in the previous 30 days:",
                "intervention trend:",
                "Most improved intervention coverage trend versus the previous window:",
            ],
            expected_resolved_intent="comparison_summary",
            expected_plan_goal="comparison",
        ),
        Case(
            role="admin",
            prompt="is intervention coverage improving for rural students",
            expected_substrings=[
                "checked the recent `region` trend for the requested imported subset",
                "Rural intervention coverage in the last 30 days:",
                "Rural intervention coverage in the previous 30 days:",
                "Rural intervention trend:",
            ],
            expected_resolved_intent="comparison_summary",
            expected_plan_goal="comparison",
        ),
        Case(
            role="counsellor",
            prompt="who should i focus on first",
            expected_substrings=[
                "students in the current faculty priority queue assigned to your counsellor scope",
                "priority",
            ],
            expected_resolved_intent="counsellor_priority_follow_up",
            expected_plan_goal="priority_queue",
        ),
        Case(
            role="counsellor",
            prompt="how many high risk students are there",
            expected_substrings=[
                "students in the latest high-risk cohort assigned to your counsellor scope",
            ],
            expected_resolved_intent="cohort_summary",
            expected_plan_goal=None,
        ),
        Case(
            role="student",
            prompt="am i likely to drop out",
            expected_substrings=[
                "Your latest risk level is",
                "Final risk probability:",
            ],
            expected_resolved_intent="student_self_risk",
            expected_plan_goal="self_risk",
        ),
    ]

    failures: list[str] = []
    for index, case in enumerate(cases, start=1):
        username, password = _credentials_for_role(case.role)
        token = _login(client, username, password)
        session_id = _create_session(client, token, f"CB22 Verify {case.role} {index}", case.expected_version)
        payload = _send(client, token, session_id, case.prompt)
        content = str(payload["assistant_message"]["content"])
        metadata = payload["assistant_message"]["metadata_json"]
        plan = metadata.get("query_plan") or {}
        planner_execution = metadata.get("planner_execution") or {}
        missing = [item for item in case.expected_substrings if item not in content]
        if missing:
            failures.append(f"Case {index} `{case.prompt}` missing: {', '.join(missing)}")
        if case.expected_resolved_intent and metadata.get("resolved_intent") != case.expected_resolved_intent:
            failures.append(
                f"Case {index} `{case.prompt}` expected resolved_intent `{case.expected_resolved_intent}`, got `{metadata.get('resolved_intent')}`"
            )
        if case.expected_plan_goal and plan.get("user_goal") != case.expected_plan_goal:
            failures.append(
                f"Case {index} `{case.prompt}` expected planner goal `{case.expected_plan_goal}`, got `{plan.get('user_goal')}`"
            )
        if str(plan.get("version")) != case.expected_version:
            failures.append(
                f"Case {index} `{case.prompt}` expected planner version `{case.expected_version}`, got `{plan.get('version')}`"
            )
        if str(planner_execution.get("planner_version")) != case.expected_version:
            failures.append(
                f"Case {index} `{case.prompt}` expected planner_execution version `{case.expected_version}`, got `{planner_execution.get('planner_version')}`"
            )
        if metadata.get("phase") != "CB22":
            failures.append(
                f"Case {index} `{case.prompt}` expected phase `CB22`, got `{metadata.get('phase')}`"
            )
        should_expect_steps = (case.expected_plan_goal in {"comparison", "attention_analysis", "diagnostic_comparison", "priority_queue"})
        if should_expect_steps and not list(planner_execution.get("orchestration_steps") or []):
            failures.append(f"Case {index} `{case.prompt}` expected non-empty orchestration steps.")
        print(f"[case {index}] role={case.role} prompt={case.prompt}")
        print(content)
        print(plan)
        print(planner_execution)
        print("-" * 40)

    if failures:
        print("CB22 planner core verification failed:")
        for failure in failures:
            print(failure)
        raise SystemExit(1)

    print("CB22 planner core verification passed.")


if __name__ == "__main__":
    main()
