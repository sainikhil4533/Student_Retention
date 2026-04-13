from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import app


def _login(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/auth/login", json={"username": username, "password": password})
    response.raise_for_status()
    return response.json()


def main() -> None:
    failures: list[str] = []
    client = TestClient(app)

    student = _login(client, "student_880001", "student_880001")
    counsellor = _login(client, "counsellor_demo", "counsellor_demo")
    admin = _login(client, "admin_demo", "admin_demo")

    if student.get("role") != "student":
        failures.append("Student login did not return role `student`.")
    if counsellor.get("role") != "counsellor":
        failures.append("Counsellor login did not return role `counsellor`.")
    if admin.get("role") != "admin":
        failures.append("Admin login did not return role `admin`.")

    student_headers = {"Authorization": f"Bearer {student['access_token']}"}
    counsellor_headers = {"Authorization": f"Bearer {counsellor['access_token']}"}
    admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}

    me = client.get("/auth/me", headers=student_headers)
    me.raise_for_status()
    if me.json().get("student_id") != 880001:
        failures.append("Student /auth/me did not preserve the student binding.")

    student_overview = client.get("/student/me/overview", headers=student_headers)
    if student_overview.status_code == 200:
        overview_payload = student_overview.json()
        if overview_payload.get("student_id") != 880001:
            failures.append("Student overview returned the wrong student_id.")
    elif student_overview.status_code != 404:
        failures.append(
            f"Student overview should return 200 or 404, got {student_overview.status_code}."
        )

    student_timeline = client.get("/timeline/880001", headers=student_headers)
    if student_timeline.status_code == 200:
        timeline_payload = student_timeline.json()
        if timeline_payload.get("student_id") != 880001:
            failures.append("Student should now be able to load their own timeline.")
    else:
        failures.append(
            f"Student timeline should now be reachable for the same student, got {student_timeline.status_code}."
        )

    queue = client.get("/faculty/priority-queue", headers=counsellor_headers)
    queue.raise_for_status()
    if "queue" not in queue.json():
        failures.append("Counsellor priority queue response is missing `queue`.")

    admin_overview = client.get("/institution/risk-overview", headers=admin_headers)
    admin_overview.raise_for_status()
    if "department_buckets" not in admin_overview.json():
        failures.append("Admin institution overview is missing `department_buckets`.")

    imports_page_check = client.get("/reports/import-coverage", headers=admin_headers)
    imports_page_check.raise_for_status()
    if "total_imported_students" not in imports_page_check.json():
        failures.append("Admin import coverage response is missing `total_imported_students`.")

    if failures:
        print("Frontend phase F1-F4 verification failed:")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("Frontend phase F1-F4 verification passed.")


if __name__ == "__main__":
    main()
