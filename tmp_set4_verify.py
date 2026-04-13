from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import app


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/auth/login", json={"username": username, "password": password})
    response.raise_for_status()
    return response.json()["access_token"]


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

    admin_token = _login(client, "admin_demo", "admin_demo")
    diagnostic_session = _create_session(client, admin_token, "CB22 Set4 Diagnostic")
    diagnostic_payload = _send(
        client,
        admin_token,
        diagnostic_session,
        "compare Urban vs Rural students and tell me what is driving the gap",
    )
    diagnostic_content = str(diagnostic_payload["assistant_message"]["content"])
    diagnostic_meta = diagnostic_payload["assistant_message"]["metadata_json"]
    diagnostic_plan = diagnostic_meta.get("query_plan") or {}
    diagnostic_execution = diagnostic_meta.get("planner_execution") or {}
    diagnostic_expected = [
        "diagnosed the requested `region` buckets",
        "Primary driver:",
        "diagnostic snapshot:",
    ]
    missing = [item for item in diagnostic_expected if item not in diagnostic_content]
    if missing:
        failures.append(f"Diagnostic case missing: {', '.join(missing)}")
    if diagnostic_meta.get("resolved_intent") != "diagnostic_comparison_summary":
        failures.append(
            f"Diagnostic case expected resolved_intent `diagnostic_comparison_summary`, got `{diagnostic_meta.get('resolved_intent')}`"
        )
    if diagnostic_plan.get("analysis_mode") != "diagnostic_comparison":
        failures.append(
            f"Diagnostic case expected analysis_mode `diagnostic_comparison`, got `{diagnostic_plan.get('analysis_mode')}`"
        )
    if diagnostic_execution.get("planner_version") != "cb22":
        failures.append(
            f"Diagnostic case expected planner_execution version `cb22`, got `{diagnostic_execution.get('planner_version')}`"
        )
    if not list(diagnostic_execution.get("orchestration_steps") or []):
        failures.append("Diagnostic case expected non-empty orchestration_steps.")

    burden_session = _create_session(client, admin_token, "CB22 Set4 Burden")
    burden_payload = _send(client, admin_token, burden_session, "which branch has the highest unresolved risk burden")
    burden_content = str(burden_payload["assistant_message"]["content"])
    burden_expected = [
        "unresolved risk burden:",
        "Highest unresolved risk burden:",
    ]
    missing = [item for item in burden_expected if item not in burden_content]
    if missing:
        failures.append(f"Burden case missing: {', '.join(missing)}")

    counsellor_token = _login(client, "counsellor_demo", "counsellor_demo")
    counsellor_session = _create_session(client, counsellor_token, "CB22 Set4 Counsellor Scope")
    counsellor_payload = _send(client, counsellor_token, counsellor_session, "who should i focus on first")
    counsellor_content = str(counsellor_payload["assistant_message"]["content"])
    counsellor_meta = counsellor_payload["assistant_message"]["metadata_json"]
    if "assigned to your counsellor scope" not in counsellor_content:
        failures.append("Counsellor scope case did not preserve assignment-scoped queue wording.")
    if counsellor_meta.get("phase") != "CB22":
        failures.append(f"Counsellor scope case expected phase `CB22`, got `{counsellor_meta.get('phase')}`")

    if failures:
        print("Set 4 verification failed:")
        for failure in failures:
            print(failure)
        raise SystemExit(1)

    print("Set 4 verification passed.")


if __name__ == "__main__":
    main()
