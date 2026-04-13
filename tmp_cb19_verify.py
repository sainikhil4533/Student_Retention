from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.main import app
from src.api.copilot_semantic_planner import plan_copilot_query_with_semantic_assist


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
    failures: list[str] = []

    with patch("src.api.copilot_semantic_planner._semantic_planner_available", return_value=True), patch(
        "src.api.copilot_semantic_planner._call_semantic_planner",
        return_value={
            "action": "rewrite",
            "rewritten_message": "which branch needs attention first and why",
            "clarification_question": "",
            "refusal_reason": "",
            "confidence": 0.93,
            "rationale": "Mapped strain phrasing to grounded attention analysis.",
        },
    ):
        plan, metadata = plan_copilot_query_with_semantic_assist(
            role="admin",
            message="who's under the heaviest strain right now and why",
            session_messages=[],
            profiles=[],
        )
        if plan.user_goal != "attention_analysis":
            failures.append(f"Expected attention_analysis after rewrite, got `{plan.user_goal}`.")
        if metadata.get("used") is not True or metadata.get("status") != "rewritten":
            failures.append(f"Expected semantic rewrite metadata, got `{metadata}`.")
        if plan.normalized_message != "which branch needs attention first and why":
            failures.append("Expected rewritten normalized_message for attention analysis case.")

    with patch("src.api.copilot_semantic_planner._semantic_planner_available", return_value=True), patch(
        "src.api.copilot_semantic_planner._call_semantic_planner",
        return_value={
            "action": "rewrite",
            "rewritten_message": "which region has the highest warning-to-intervention gap",
            "clarification_question": "",
            "refusal_reason": "",
            "confidence": 0.9,
            "rationale": "Mapped support-gap phrasing to grounded warning/intervention gap comparison.",
        },
    ):
        plan, metadata = plan_copilot_query_with_semantic_assist(
            role="admin",
            message="where is the support gap worst across regions",
            session_messages=[],
            profiles=[],
        )
        if plan.user_goal != "comparison":
            failures.append(f"Expected comparison after support-gap rewrite, got `{plan.user_goal}`.")
        if "warning_intervention_gap" not in list(plan.metrics):
            failures.append(f"Expected warning_intervention_gap metric after rewrite, got `{plan.metrics}`.")
        if metadata.get("used") is not True:
            failures.append("Expected semantic planner to be used for support-gap rewrite.")

    with patch("src.api.copilot_semantic_planner._semantic_planner_available", return_value=True), patch(
        "src.api.copilot_semantic_planner._call_semantic_planner",
        return_value={
            "action": "clarify",
            "rewritten_message": "",
            "clarification_question": "Do you want me to compare by branch or by region first?",
            "refusal_reason": "",
            "confidence": 0.88,
            "rationale": "Detected competing comparison dimensions.",
        },
    ):
        plan, metadata = plan_copilot_query_with_semantic_assist(
            role="admin",
            message="compare CSE and ECE students in Urban and Rural but what's driving it",
            session_messages=[],
            profiles=[],
        )
        if not plan.clarification_needed:
            failures.append("Expected clarification-needed plan from semantic planner.")
        if "branch or by region" not in str(plan.clarification_question or ""):
            failures.append("Expected semantic clarification question to be preserved.")
        if metadata.get("status") != "clarification":
            failures.append(f"Expected clarification metadata status, got `{metadata.get('status')}`.")

    client = TestClient(app)
    admin_token = _login(client, "admin_demo", "admin_demo")
    session_id = _create_session(client, admin_token, "CB19 live fallback smoke")
    payload = _send(client, admin_token, session_id, "which branch needs attention first and why")
    metadata = payload["assistant_message"]["metadata_json"]
    semantic = metadata.get("semantic_planner") or {}
    if metadata.get("phase") != "CB22":
        failures.append(f"Live app expected phase `CB22`, got `{metadata.get('phase')}`.")
    if semantic.get("phase") != "CB19":
        failures.append(f"Live app expected semantic planner phase `CB19`, got `{semantic.get('phase')}`.")
    if "status" not in semantic:
        failures.append("Live app missing semantic planner status metadata.")

    if failures:
        print("CB19 verification failed:")
        for failure in failures:
            print(failure)
        raise SystemExit(1)

    print("CB19 verification passed.")


if __name__ == "__main__":
    main()
