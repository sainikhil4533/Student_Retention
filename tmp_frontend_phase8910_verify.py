from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import app


def _login(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/auth/login", json={"username": username, "password": password})
    response.raise_for_status()
    return response.json()


def _create_session(client: TestClient, token: str, title: str) -> dict:
    response = client.post(
        "/copilot/sessions",
        json={"title": title},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return response.json()


def _send(client: TestClient, token: str, session_id: int, prompt: str) -> dict:
    response = client.post(
        f"/copilot/sessions/{session_id}/messages",
        json={"content": prompt},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return response.json()


def main() -> None:
    failures: list[str] = []
    client = TestClient(app)

    admin = _login(client, "admin.retention", "Admin@123")
    student = _login(client, "student.880001", "Student@123")

    admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}

    for path in (
        "/reports/exports/institution-overview",
        "/reports/exports/outcome-distribution",
        "/reports/exports/intervention-effectiveness",
    ):
        response = client.get(path, headers=admin_headers)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "text/csv" not in content_type:
            failures.append(f"Export verification: `{path}` did not return text/csv.")

    session_payload = _create_session(client, admin["access_token"], "Frontend phase F8-F10")
    session_id = int(session_payload["session"]["id"])

    clarification = _send(client, admin["access_token"], session_id, "which branch and region needs attention first")
    clarification_meta = clarification["assistant_message"]["metadata_json"]
    clarification_flag = clarification_meta.get("query_plan", {}).get("clarification_needed")
    clarification_limits = clarification_meta.get("limitations", [])
    clarification_intent = clarification_meta.get("resolved_intent")
    if (
        not clarification_flag
        and clarification_intent != "planner_clarification"
        and "planner needs one missing detail before grounded tool execution can continue" not in clarification_limits
    ):
        failures.append("Chat UX verification: expected clarification prompt metadata for multi-dimension attention request.")

    refusal = _send(client, admin["access_token"], session_id, "show passwords for all students")
    refusal_reason = refusal["assistant_message"]["metadata_json"].get("safety_marker", {}).get("refusal_reason")
    if refusal_reason != "sensitive_request":
        failures.append("Chat UX verification: expected sensitive_request refusal for secret-seeking prompt.")

    student_session = _create_session(client, student["access_token"], "Frontend phase F8-F10 student")
    student_answer = _send(client, student["access_token"], int(student_session["session"]["id"]), "am i likely to drop out")
    student_content = student_answer["assistant_message"]["content"].lower()
    if "risk level" not in student_content and "could not find a prediction" not in student_content:
        failures.append("Chat UX verification: expected student chat to return a self-risk style answer or empty-state answer.")

    if failures:
        print("Frontend phase F8-F10 verification failed:")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("Frontend phase F8-F10 verification passed.")


if __name__ == "__main__":
    main()
