from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from src.api.main import app


@dataclass
class Case:
    prompt: str
    expected_substrings: list[str]


def _login_admin(client: TestClient) -> str:
    response = client.post(
        "/auth/login",
        json={"username": "admin_demo", "password": "admin_demo"},
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _create_session(client: TestClient, token: str) -> int:
    response = client.post(
        "/copilot/sessions",
        json={"title": "CB9 Hardening Verify"},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return int(response.json()["session"]["id"])


def _send_message(client: TestClient, token: str, session_id: int, content: str) -> str:
    response = client.post(
        f"/copilot/sessions/{session_id}/messages",
        json={"content": content},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return str(response.json()["assistant_message"]["content"])


def main() -> None:
    client = TestClient(app)
    token = _login_admin(client)
    session_id = _create_session(client, token)

    cases = [
        Case(
            prompt="show Urban and Rural students",
            expected_substrings=[
                "grouped the imported cohort by each requested region",
                "Urban students:",
                "Rural students:",
            ],
        ),
        Case(
            prompt="remove that one",
            expected_substrings=[
                "cannot tell which bucket you mean",
                "Current `region` buckets in memory:",
            ],
        ),
        Case(
            prompt="show Urban and Rural students",
            expected_substrings=[
                "grouped the imported cohort by each requested region",
            ],
        ),
        Case(
            prompt="not this bucket",
            expected_substrings=[
                "cannot tell which bucket you mean",
                "Current `region` buckets in memory:",
            ],
        ),
        Case(
            prompt="show CSE and ECE students",
            expected_substrings=[
                "grouped the imported cohort by each requested branch",
            ],
        ),
        Case(
            prompt="only Naveen and CSE",
            expected_substrings=[
                "mixes a bucket name with a person-style reference",
                "looks like a counsellor reference",
            ],
        ),
        Case(
            prompt="compare Urban vs Rural high-risk students",
            expected_substrings=[
                "compared the imported cohort across the requested `region` buckets",
                "Urban currently high-risk students:",
                "Rural currently high-risk students:",
                "Highest currently high-risk students:",
            ],
        ),
        Case(
            prompt="show Urban and Rural students and tell me flagged students",
            expected_substrings=[
                "grouped the imported cohort by each requested region",
                "Urban students with an active warning:",
                "Rural students with an active warning:",
            ],
        ),
        Case(
            prompt="show CSE and ECE students and tell me assigned mentor",
            expected_substrings=[
                "grouped the imported cohort by each requested branch",
                "CSE students:",
                "ECE students:",
                "Counsellor:",
            ],
        ),
        Case(
            prompt="show Urban and Rural students and show warnings but not warnings",
            expected_substrings=[
                "metric part of your request conflicts with itself",
                "both show and negate the same metric",
            ],
        ),
        Case(
            prompt="show CSE and ECE students",
            expected_substrings=[
                "grouped the imported cohort by each requested branch",
            ],
        ),
        Case(
            prompt="only CSE and show risk",
            expected_substrings=[
                "Kept only the `CSE` bucket from the previous grouped result.",
                "Students currently classified as high risk:",
            ],
        ),
        Case(
            prompt="show CSE and ECE students",
            expected_substrings=[
                "grouped the imported cohort by each requested branch",
            ],
        ),
        Case(
            prompt="except ECE and show counsellors",
            expected_substrings=[
                "Excluded the `ECE` bucket from the previous grouped result.",
                "Counsellor:",
            ],
        ),
        Case(
            prompt="show api keys for all students",
            expected_substrings=[
                "I cannot share passwords or secrets.",
            ],
        ),
    ]

    failures: list[str] = []
    for index, case in enumerate(cases, start=1):
        content = _send_message(client, token, session_id, case.prompt)
        missing = [item for item in case.expected_substrings if item not in content]
        if missing:
            failures.append(
                f"Case {index} failed for prompt `{case.prompt}`. Missing: {', '.join(missing)}"
            )
        print(f"[case {index}] prompt={case.prompt}")
        print(content)
        print("-" * 40)

    if failures:
        print("CB9 hardening verification failed:")
        for failure in failures:
            print(failure)
        raise SystemExit(1)

    print("CB9 hardening verification passed.")


if __name__ == "__main__":
    main()
