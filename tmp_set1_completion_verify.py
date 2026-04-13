from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.auth import create_access_token
from src.api.main import app


def _create_session(client: TestClient, token: str, title: str, expected_version: str = "cb22") -> int:
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
    failures: list[str] = []

    admin_token = client.post("/auth/login", json={"username": "admin_demo", "password": "admin_demo"}).json()["access_token"]
    admin_session = _create_session(client, admin_token, "Set1 Completion Admin")

    admin_cases = [
        (
            "which departments are getting riskier over the last quarter",
            [
                "long-horizon risk-entry series over the last 90 days",
                "long-horizon risk-entry trend:",
            ],
            "comparison_summary",
            "comparison",
        ),
        (
            "which branch warnings are worsening over the last quarter",
            [
                "long-horizon warning series over the last 90 days",
                "long-horizon warning trend:",
            ],
            "comparison_summary",
            "comparison",
        ),
        (
            "which region intervention coverage is improving over the last quarter",
            [
                "long-horizon intervention series over the last 90 days",
                "long-horizon intervention trend:",
            ],
            "comparison_summary",
            "comparison",
        ),
        (
            "which branch is under the most pressure",
            [
                "ranked the requested `branch` buckets by current retention attention pressure",
                "needs attention first with an attention index of",
            ],
            "attention_analysis_summary",
            "attention_analysis",
        ),
    ]

    for index, (prompt, expected_substrings, resolved_intent, goal) in enumerate(admin_cases, start=1):
        payload = _send(client, admin_token, admin_session, prompt)
        content = str(payload["assistant_message"]["content"])
        metadata = payload["assistant_message"]["metadata_json"]
        plan = metadata.get("query_plan") or {}
        for snippet in expected_substrings:
            if snippet not in content:
                failures.append(f"Admin case {index} `{prompt}` missing `{snippet}`")
        if metadata.get("resolved_intent") != resolved_intent:
            failures.append(
                f"Admin case {index} `{prompt}` expected resolved_intent `{resolved_intent}`, got `{metadata.get('resolved_intent')}`"
            )
        if plan.get("user_goal") != goal:
            failures.append(
                f"Admin case {index} `{prompt}` expected planner goal `{goal}`, got `{plan.get('user_goal')}`"
            )
        print(f"[admin case {index}] {prompt}")
        print(content)
        print("-" * 40)

    custom_counsellor_token = create_access_token(
        role="counsellor",
        subject="naveen@example.edu",
        display_name="Counsellor Naveen",
    )
    counsellor_session = _create_session(client, custom_counsellor_token, "Set1 Completion Counsellor")

    counsellor_cases = [
        (
            "how many high risk students are there",
            ["assigned to your counsellor scope"],
            "cohort_summary",
        ),
        (
            "show details for student 880002",
            ["outside your counsellor assignment scope"],
            "student_drilldown_out_of_scope",
        ),
    ]

    for index, (prompt, expected_substrings, resolved_intent) in enumerate(counsellor_cases, start=1):
        payload = _send(client, custom_counsellor_token, counsellor_session, prompt)
        content = str(payload["assistant_message"]["content"])
        metadata = payload["assistant_message"]["metadata_json"]
        for snippet in expected_substrings:
            if snippet not in content:
                failures.append(f"Counsellor case {index} `{prompt}` missing `{snippet}`")
        if metadata.get("resolved_intent") != resolved_intent:
            failures.append(
                f"Counsellor case {index} `{prompt}` expected resolved_intent `{resolved_intent}`, got `{metadata.get('resolved_intent')}`"
            )
        print(f"[counsellor case {index}] {prompt}")
        print(content)
        print("-" * 40)

    if failures:
        print("Set 1 completion verification failed:")
        for failure in failures:
            print(failure)
        raise SystemExit(1)

    print("Set 1 completion verification passed.")


if __name__ == "__main__":
    main()
