from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from src.api.main import app


@dataclass
class Case:
    prompt: str
    expected_substrings: list[str]


def _login(client: TestClient) -> str:
    response = client.post("/auth/login", json={"username": "admin_demo", "password": "admin_demo"})
    response.raise_for_status()
    return response.json()["access_token"]


def _create_session(client: TestClient, token: str, title: str) -> int:
    response = client.post(
        "/copilot/sessions",
        json={"title": title},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    payload = response.json()
    assert payload["session"]["system_prompt_version"] == "cb22"
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
    token = _login(client)
    session_id = _create_session(client, token, "CB22 summary smoke")
    failures: list[str] = []

    cases = [
        Case(
            prompt="compare dropped students in CSE vs ECE by warnings and counsellor coverage",
            expected_substrings=[
                "CSE counsellor coverage:",
                "ECE counsellor coverage:",
                "Highest counsellor coverage:",
                "Lowest counsellor coverage:",
            ],
        ),
        Case(
            prompt="which branch has the worst dropped-to-warning overlap",
            expected_substrings=[
                "dropped-to-warning overlap:",
                "Worst dropped-to-warning overlap:",
            ],
        ),
        Case(
            prompt="which departments saw the most students newly enter risk in the last 30 days",
            expected_substrings=[
                "newly high-risk students in the last 30 days:",
                "Highest newly high-risk students in the last 30 days:",
            ],
        ),
        Case(
            prompt="which departments are getting riskier lately",
            expected_substrings=[
                "risk-entry trend:",
                "Most worsening recent high-risk-entry trend versus the previous window:",
            ],
        ),
        Case(
            prompt="which region intervention coverage is improving",
            expected_substrings=[
                "intervention trend:",
                "Most improved intervention coverage trend versus the previous window:",
            ],
        ),
        Case(
            prompt="which region has the highest warning-to-intervention gap",
            expected_substrings=[
                "warning-to-intervention gap:",
                "Largest warning-to-intervention gap:",
            ],
        ),
    ]

    for index, case in enumerate(cases, start=1):
        payload = _send(client, token, session_id, case.prompt)
        content = str(payload["assistant_message"]["content"])
        missing = [item for item in case.expected_substrings if item not in content]
        if missing:
            failures.append(f"Case {index} `{case.prompt}` missing: {', '.join(missing)}")
        print(f"[cb22 summary case {index}] {case.prompt}")
        print(content)
        print("-" * 40)

    if failures:
        print("CB22 summary smoke verification failed:")
        for failure in failures:
            print(failure)
        raise SystemExit(1)

    print("CB22 summary smoke verification passed.")


if __name__ == "__main__":
    main()
