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
        json={"title": "Bucket Followup Verify"},
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
            prompt="exclude the Rural bucket",
            expected_substrings=[
                "excluded the `Rural` bucket from the previous grouped result",
                "Matching students:",
            ],
        ),
        Case(
            prompt="show CSE and ECE students",
            expected_substrings=[
                "grouped the imported cohort by each requested branch",
                "CSE students:",
                "ECE students:",
            ],
        ),
        Case(
            prompt="show everything except CSE",
            expected_substrings=[
                "excluded the `CSE` bucket from the previous grouped result",
                "Matching students:",
            ],
        ),
        Case(
            prompt="show CSE and ECE students",
            expected_substrings=[
                "grouped the imported cohort by each requested branch",
                "CSE students:",
                "ECE students:",
            ],
        ),
        Case(
            prompt="show everything except CSE and tell me how many are high risk",
            expected_substrings=[
                "Excluded the `CSE` bucket from the previous grouped result.",
                "Students currently classified as high risk:",
            ],
        ),
        Case(
            prompt="show Urban and Rural students",
            expected_substrings=[
                "grouped the imported cohort by each requested region",
                "Urban students:",
                "Rural students:",
            ],
        ),
        Case(
            prompt="exclude the Rural bucket and show warnings",
            expected_substrings=[
                "Excluded the `Rural` bucket from the previous grouped result.",
                "Students with an active warning:",
            ],
        ),
        Case(
            prompt="show CSE and ECE students",
            expected_substrings=[
                "grouped the imported cohort by each requested branch",
                "CSE students:",
                "ECE students:",
            ],
        ),
        Case(
            prompt="show everything except CSE and tell me counsellors",
            expected_substrings=[
                "Excluded the `CSE` bucket from the previous grouped result.",
                "Counsellor:",
            ],
        ),
        Case(
            prompt="show Urban and Rural students",
            expected_substrings=[
                "grouped the imported cohort by each requested region",
                "Urban students:",
                "Rural students:",
            ],
        ),
        Case(
            prompt="show only the Rural bucket and tell me warnings",
            expected_substrings=[
                "Kept only the `Rural` bucket from the previous grouped result.",
                "Students with an active warning:",
            ],
        ),
        Case(
            prompt="show CSE and ECE students",
            expected_substrings=[
                "grouped the imported cohort by each requested branch",
                "CSE students:",
                "ECE students:",
            ],
        ),
        Case(
            prompt="only CSE and show counsellors",
            expected_substrings=[
                "Kept only the `CSE` bucket from the previous grouped result.",
                "Counsellor:",
            ],
        ),
        Case(
            prompt="show CSE and ECE students",
            expected_substrings=[
                "grouped the imported cohort by each requested branch",
                "CSE students:",
                "ECE students:",
            ],
        ),
        Case(
            prompt="what about ECE and risk only",
            expected_substrings=[
                "Kept only the `ECE` bucket from the previous grouped result.",
                "Students currently classified as high risk:",
            ],
        ),
        Case(
            prompt="show CSE and ECE students",
            expected_substrings=[
                "grouped the imported cohort by each requested branch",
                "CSE students:",
                "ECE students:",
            ],
        ),
        Case(
            prompt="only CSE and ECE and show risk",
            expected_substrings=[
                "Kept only these buckets from the previous grouped result: `CSE`, `ECE`.",
                "Students currently classified as high risk:",
            ],
        ),
        Case(
            prompt="show CSE and ECE students",
            expected_substrings=[
                "grouped the imported cohort by each requested branch",
                "CSE students:",
                "ECE students:",
            ],
        ),
        Case(
            prompt="only CSE but exclude CSE",
            expected_substrings=[
                "bucket instruction conflicts with itself",
                "both keep and exclude the same bucket",
            ],
        ),
        Case(
            prompt="show CSE and ECE students",
            expected_substrings=[
                "grouped the imported cohort by each requested branch",
                "CSE students:",
                "ECE students:",
            ],
        ),
        Case(
            prompt="only SC",
            expected_substrings=[
                "switching to a different dimension",
                "current grouped result is by `branch`",
            ],
        ),
        Case(
            prompt="show Urban and Rural students",
            expected_substrings=[
                "grouped the imported cohort by each requested region",
                "Urban students:",
                "Rural students:",
            ],
        ),
        Case(
            prompt="Rural warnings only",
            expected_substrings=[
                "Kept only the `Rural` bucket from the previous grouped result.",
                "Students with an active warning:",
            ],
        ),
        Case(
            prompt="show Urban and Rural students",
            expected_substrings=[
                "grouped the imported cohort by each requested region",
                "Urban students:",
                "Rural students:",
            ],
        ),
        Case(
            prompt="except Urban counsellors",
            expected_substrings=[
                "Excluded the `Urban` bucket from the previous grouped result.",
                "Counsellor:",
            ],
        ),
        Case(
            prompt="show Urban and Rural students",
            expected_substrings=[
                "grouped the imported cohort by each requested region",
                "Urban students:",
                "Rural students:",
            ],
        ),
        Case(
            prompt="only Naveen",
            expected_substrings=[
                "reference is ambiguous",
                "matches a counsellor name",
            ],
        ),
        Case(
            prompt="show CSE and ECE students in Urban and Rural",
            expected_substrings=[
                "grouped the imported cohort by branch and region",
                "CSE / Urban students:",
                "ECE / Rural students:",
            ],
        ),
        Case(
            prompt="show CSE and ECE students",
            expected_substrings=[
                "grouped the imported cohort by each requested branch",
                "CSE students:",
                "ECE students:",
            ],
        ),
        Case(
            prompt="only those",
            expected_substrings=[
                "cannot tell which bucket you mean",
                "Current `branch` buckets in memory:",
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
        print("Bucket follow-up verification failed:")
        for failure in failures:
            print(failure)
        raise SystemExit(1)

    print("Bucket follow-up verification passed.")


if __name__ == "__main__":
    main()
