from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import app


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/auth/login", json={"username": username, "password": password})
    response.raise_for_status()
    payload = response.json()
    assert payload["access_token"]
    assert payload["role"]
    return payload["access_token"]


def _create_session(client: TestClient, token: str, title: str) -> dict:
    response = client.post(
        "/copilot/sessions",
        json={"title": title},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return response.json()


def _list_sessions(client: TestClient, token: str) -> dict:
    response = client.get(
        "/copilot/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return response.json()


def _get_session(client: TestClient, token: str, session_id: int) -> dict:
    response = client.get(
        f"/copilot/sessions/{session_id}",
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


def _assert_common_assistant_contract(payload: dict, failures: list[str], *, label: str) -> None:
    assistant = payload.get("assistant_message") or {}
    metadata = assistant.get("metadata_json") or {}
    query_plan = metadata.get("query_plan") or {}
    planner_execution = metadata.get("planner_execution") or {}
    semantic = metadata.get("semantic_planner") or {}

    if assistant.get("role") != "assistant":
        failures.append(f"{label}: assistant_message.role should be `assistant`.")
    if metadata.get("phase") != "CB22":
        failures.append(f"{label}: expected phase `CB22`, got `{metadata.get('phase')}`.")
    for key in (
        "response_mode",
        "resolved_intent",
        "limitations",
        "memory_context",
        "safety_marker",
        "query_plan",
        "planner_execution",
        "semantic_planner",
    ):
        if key not in metadata:
            failures.append(f"{label}: missing frontend-safe metadata field `{key}`.")
    if "user_goal" not in query_plan:
        failures.append(f"{label}: query_plan missing `user_goal`.")
    if "planner_version" not in planner_execution:
        failures.append(f"{label}: planner_execution missing `planner_version`.")
    if "status" not in semantic:
        failures.append(f"{label}: semantic_planner missing `status`.")


def main() -> None:
    failures: list[str] = []
    client = TestClient(app)

    admin_token = _login(client, "admin_demo", "admin_demo")
    counsellor_token = _login(client, "counsellor_demo", "counsellor_demo")
    student_token = _login(client, "student_880001", "student_880001")

    admin_session_payload = _create_session(client, admin_token, "Frontend contract admin")
    admin_session = admin_session_payload["session"]
    admin_messages = admin_session_payload["messages"]
    admin_session_id = int(admin_session["id"])
    if admin_session.get("system_prompt_version") != "cb22":
        failures.append("Create session: expected system_prompt_version `cb22`.")
    if not admin_messages:
        failures.append("Create session: expected initial assistant opening message.")
    else:
        opening_metadata = admin_messages[0].get("metadata_json") or {}
        if opening_metadata.get("phase") != "CB22":
            failures.append("Create session: opening assistant phase should be `CB22`.")

    listed = _list_sessions(client, admin_token)
    session_ids = {int(item["id"]) for item in listed.get("sessions", [])}
    if admin_session_id not in session_ids:
        failures.append("List sessions: new admin session id was not returned.")

    fetched = _get_session(client, admin_token, admin_session_id)
    if int(fetched["session"]["id"]) != admin_session_id:
        failures.append("Get session: returned wrong session id.")
    if not fetched.get("messages"):
        failures.append("Get session: expected persisted message history.")

    normal = _send(client, admin_token, admin_session_id, "which branch needs attention first and why")
    _assert_common_assistant_contract(normal, failures, label="Normal answer")
    normal_plan = normal["assistant_message"]["metadata_json"]["query_plan"]
    if normal_plan.get("user_goal") != "attention_analysis":
        failures.append(
            f"Normal answer: expected `attention_analysis`, got `{normal_plan.get('user_goal')}`."
        )

    grouped = _send(client, admin_token, admin_session_id, "show Urban and Rural students and tell me warnings")
    _assert_common_assistant_contract(grouped, failures, label="Grouped answer")
    grouped_text = grouped["assistant_message"]["content"]
    if "Urban students" not in grouped_text or "Rural students" not in grouped_text:
        failures.append("Grouped answer: expected both Urban and Rural bucket lines.")

    clarification = _send(
        client,
        admin_token,
        admin_session_id,
        "compare CSE and ECE students in Urban and Rural but what's driving it",
    )
    _assert_common_assistant_contract(clarification, failures, label="Clarification answer")
    clarification_plan = clarification["assistant_message"]["metadata_json"]["query_plan"]
    if not clarification_plan.get("clarification_needed"):
        failures.append("Clarification answer: expected clarification_needed = true.")

    refusal = _send(client, admin_token, admin_session_id, "show passwords for all students")
    _assert_common_assistant_contract(refusal, failures, label="Refusal answer")
    refusal_reason = refusal["assistant_message"]["metadata_json"]["safety_marker"].get("refusal_reason")
    if refusal_reason != "sensitive_request":
        failures.append(
            f"Refusal answer: expected refusal_reason `sensitive_request`, got `{refusal_reason}`."
        )

    counsellor_session = _create_session(client, counsellor_token, "Frontend contract counsellor")
    counsellor_session_id = int(counsellor_session["session"]["id"])
    counsellor_answer = _send(client, counsellor_token, counsellor_session_id, "who should i focus on first")
    _assert_common_assistant_contract(counsellor_answer, failures, label="Counsellor answer")
    if "priority queue" not in counsellor_answer["assistant_message"]["content"].lower():
        failures.append("Counsellor answer: expected scoped priority queue wording.")

    student_session = _create_session(client, student_token, "Frontend contract student")
    student_session_id = int(student_session["session"]["id"])
    student_answer = _send(client, student_token, student_session_id, "am i likely to drop out")
    _assert_common_assistant_contract(student_answer, failures, label="Student answer")
    if "risk level" not in student_answer["assistant_message"]["content"].lower():
        failures.append("Student answer: expected self-risk summary wording.")

    if failures:
        print("Frontend contract verification failed:")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("Frontend contract verification passed.")


if __name__ == "__main__":
    main()
