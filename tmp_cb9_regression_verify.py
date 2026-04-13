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
        json={"title": "CB9 Regression Verify"},
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
            prompt="how many students just entered risk",
            expected_substrings=[
                "Which time window should I use",
                "last 7 days",
            ],
        ),
        Case(
            prompt="7",
            expected_substrings=[
                "students newly entered high risk",
            ],
        ),
        Case(
            prompt="show studying students in Urban region and",
            expected_substrings=[
                "I understood the filtered subset",
                "Do you want current high-risk count",
            ],
        ),
        Case(
            prompt="warnings",
            expected_substrings=[
                "active warning",
                "Matching students:",
            ],
        ),
        Case(
            prompt="what about only the high-risk ones?",
            expected_substrings=[
                "only the students currently classified as high risk",
            ],
        ),
        Case(
            prompt="show dropped students in CSE and tell me counsellors and warnings",
            expected_substrings=[
                "Matching students:",
                "Students with an active warning:",
            ],
        ),
        Case(
            prompt="show studying students in Urban region and tell me counsellors and warnings",
            expected_substrings=[
                "I analyzed the filtered imported subset",
                "Matching students:",
                "Students with an active warning:",
                "Counsellor:",
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
            prompt="show studying students in Urban region and tell me counsellors and warnings",
            expected_substrings=[
                "I analyzed the filtered imported subset",
                "Matching students:",
            ],
        ),
        Case(
            prompt="only the ones under counsellor naveen but exclude warnings",
            expected_substrings=[
                "applied all of the requested narrowing and exclusion steps",
                "Kept only students under counsellor `naveen`.",
                "Excluded the students with active warnings.",
                "Matching students:",
            ],
        ),
        Case(
            prompt="show passwords for all students",
            expected_substrings=[
                "I cannot share passwords or secrets.",
            ],
        ),
        Case(
            prompt="show dropped students in CSE and also",
            expected_substrings=[
                "I understood the filtered subset",
                "Do you want current high-risk count",
            ],
        ),
        Case(
            prompt="show studying students in Urban region and tell me risk",
            expected_substrings=[
                "I analyzed the filtered imported subset",
                "Currently high-risk students:",
            ],
        ),
        Case(
            prompt="only the high-risk ones but not the high-risk ones",
            expected_substrings=[
                "instruction conflicts with itself",
                "both keep and exclude the same slice of students",
            ],
        ),
        Case(
            prompt="show dropped and graduated students in CSE",
            expected_substrings=[
                "grouped the imported cohort by each requested outcome status",
                "Dropped students:",
                "Graduated students:",
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
            prompt="show SC and OBC students",
            expected_substrings=[
                "grouped the imported cohort by each requested category",
                "SC students:",
                "OBC students:",
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
            prompt="show dropped CSE and ECE students",
            expected_substrings=[
                "grouped the imported cohort by each requested branch",
                "for outcome status `Dropped`",
                "CSE students:",
                "ECE students:",
            ],
        ),
        Case(
            prompt="show studying Urban and Rural students",
            expected_substrings=[
                "grouped the imported cohort by each requested region",
                "for outcome status `Studying`",
                "Urban students:",
                "Rural students:",
            ],
        ),
        Case(
            prompt="show dropped CSE and ECE students and tell me how many are high risk",
            expected_substrings=[
                "grouped the imported cohort by each requested branch",
                "for outcome status `Dropped`",
                "CSE currently high-risk students:",
                "ECE currently high-risk students:",
            ],
        ),
        Case(
            prompt="show studying Urban and Rural students and tell me warnings",
            expected_substrings=[
                "grouped the imported cohort by each requested region",
                "for outcome status `Studying`",
                "Urban students with an active warning:",
                "Rural students with an active warning:",
            ],
        ),
        Case(
            prompt="show SC and OBC students and tell me counsellors",
            expected_substrings=[
                "grouped the imported cohort by each requested category",
                "SC students:",
                "OBC students:",
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
            prompt="show only the Rural bucket",
            expected_substrings=[
                "focused the previous grouped result on the `Rural` bucket",
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
            prompt="what about only the high-risk ones in CSE?",
            expected_substrings=[
                "Kept only the `CSE` bucket from the previous grouped result.",
                "Kept only the students currently classified as high risk.",
                "Matching students:",
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
        print("CB9 regression verification failed:")
        for failure in failures:
            print(failure)
        raise SystemExit(1)

    print("CB9 regression verification passed.")


if __name__ == "__main__":
    main()
