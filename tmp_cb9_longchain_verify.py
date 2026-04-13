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
        json={"title": "CB9 Longchain Verify"},
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
            prompt="show Urban and Rural students and tell me warnings",
            expected_substrings=[
                "grouped the imported cohort by each requested region",
                "Urban students with an active warning:",
                "Rural students with an active warning:",
            ],
        ),
        Case(
            prompt="show only the Rural bucket",
            expected_substrings=[
                "Kept only the `Rural` bucket from the previous grouped result.",
                "Matching students:",
            ],
        ),
        Case(
            prompt="show counsellors",
            expected_substrings=[
                "summarized their counsellor coverage",
                "Matching students:",
                "Counsellor:",
            ],
        ),
        Case(
            prompt="only the high-risk ones",
            expected_substrings=[
                "Kept only the students currently classified as high risk.",
                "Matching students:",
            ],
        ),
        Case(
            prompt="exclude the ones with warnings",
            expected_substrings=[
                "Excluded the students with active warnings.",
                "Matching students:",
            ],
        ),
        Case(
            prompt="show CSE and ECE students and tell me assigned mentor",
            expected_substrings=[
                "grouped the imported cohort by each requested branch",
                "CSE Counsellor:",
                "ECE Counsellor:",
            ],
        ),
        Case(
            prompt="only CSE",
            expected_substrings=[
                "Kept only the `CSE` bucket from the previous grouped result.",
                "Matching students:",
            ],
        ),
        Case(
            prompt="show risk",
            expected_substrings=[
                "checked their current risk coverage",
                "Matching students:",
                "Students currently classified as high risk:",
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
        print("CB9 longchain verification failed:")
        for failure in failures:
            print(failure)
        raise SystemExit(1)

    print("CB9 longchain verification passed.")


if __name__ == "__main__":
    main()
