from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import app


def _login(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/auth/login", json={"username": username, "password": password})
    response.raise_for_status()
    payload = response.json()
    assert payload["access_token"]
    assert payload["role"]
    return payload


def main() -> None:
    failures: list[str] = []
    client = TestClient(app)

    student = _login(client, "student_880001", "student_880001")
    counsellor = _login(client, "counsellor_demo", "counsellor_demo")
    admin = _login(client, "admin_demo", "admin_demo")

    student_headers = {"Authorization": f"Bearer {student['access_token']}"}
    counsellor_headers = {"Authorization": f"Bearer {counsellor['access_token']}"}
    admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}

    student_overview = client.get("/student/me/overview", headers=student_headers)
    if student_overview.status_code == 200:
        overview_payload = student_overview.json()
        if overview_payload.get("student_id") != student.get("student_id"):
            failures.append("Student journey verification: overview returned the wrong student id.")
    elif student_overview.status_code != 404:
        failures.append(
            f"Student journey verification: expected /student/me/overview to return 200 or 404, got {student_overview.status_code}."
        )

    student_timeline = client.get(f"/timeline/{student['student_id']}", headers=student_headers)
    if student_timeline.status_code != 200:
        failures.append(
            f"Student journey verification: expected same-student timeline access, got {student_timeline.status_code}."
        )
    else:
        timeline_payload = student_timeline.json()
        if timeline_payload.get("student_id") != student.get("student_id"):
            failures.append("Student journey verification: timeline returned the wrong student id.")

    active_cases = client.get("/cases/active", headers=counsellor_headers)
    active_cases.raise_for_status()
    active_cases_payload = active_cases.json()
    if "total_students" not in active_cases_payload or "cases" not in active_cases_payload:
        failures.append("Counsellor workbench verification: /cases/active is missing required fields.")

    case_list = active_cases_payload.get("cases", [])
    if case_list:
        selected_student_id = int(case_list[0]["student_id"])

        context_response = client.get(f"/operations/context/{selected_student_id}", headers=counsellor_headers)
        if context_response.status_code == 200:
            context_payload = context_response.json()
            for key in ("activity_summary", "milestone_flags", "sla_summary"):
                if key not in context_payload:
                    failures.append(
                        f"Counsellor workbench verification: operational context is missing `{key}`."
                    )
        elif context_response.status_code != 404:
            failures.append(
                f"Counsellor workbench verification: expected /operations/context/{{student_id}} to return 200 or 404, got {context_response.status_code}."
            )

        history_response = client.get(
            f"/interventions/history/{selected_student_id}",
            headers=counsellor_headers,
        )
        history_response.raise_for_status()
        history_payload = history_response.json()
        if history_payload.get("student_id") != selected_student_id:
            failures.append("Counsellor workbench verification: intervention history returned the wrong student id.")
        if "interventions" not in history_payload:
            failures.append("Counsellor workbench verification: intervention history is missing `interventions`.")

    operations_response = client.get("/reports/operations-overview", headers=admin_headers)
    operations_response.raise_for_status()
    operations_payload = operations_response.json()
    for key in ("summary", "institution_overview", "intervention_effectiveness"):
        if key not in operations_payload:
            failures.append(f"Admin operations verification: operations overview is missing `{key}`.")

    import_coverage_response = client.get("/reports/import-coverage", headers=admin_headers)
    import_coverage_response.raise_for_status()
    import_coverage_payload = import_coverage_response.json()
    for key in ("total_imported_students", "scored_students", "unscored_students", "students"):
        if key not in import_coverage_payload:
            failures.append(f"Admin operations verification: import coverage is missing `{key}`.")

    if failures:
        print("Frontend phase F5-F7 verification failed:")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("Frontend phase F5-F7 verification passed.")


if __name__ == "__main__":
    main()
