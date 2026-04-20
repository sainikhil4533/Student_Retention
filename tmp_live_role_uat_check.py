from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


BASE_URL = os.getenv("RETENTION_API_BASE_URL", "http://127.0.0.1:8000")
IMPORTED_PASSWORD = os.getenv("AUTH_IMPORTED_ACCOUNT_INITIAL_PASSWORD", "Welcome@123")


def _request(
    path: str,
    *,
    method: str = "GET",
    token: str | None = None,
    body: dict | None = None,
) -> dict:
    payload = None
    headers = {"Accept": "application/json"}
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=payload,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _login(username: str, password: str) -> dict:
    return _request(
        "/auth/login",
        method="POST",
        body={"username": username, "password": password},
    )


def _copilot_roundtrip(token: str, question: str) -> str:
    session = _request(
        "/copilot/sessions",
        method="POST",
        token=token,
        body={"title": "Live UAT"},
    )
    session_id = int(session["session"]["id"])
    reply = _request(
        f"/copilot/sessions/{session_id}/messages",
        method="POST",
        token=token,
        body={"content": question},
    )
    return str(reply["assistant_message"]["content"])


def main() -> None:
    try:
        admin = _login("admin.retention", "Admin@123")
        student = _login("stu001", IMPORTED_PASSWORD)
        counsellor = _login("asha.counsellor", IMPORTED_PASSWORD)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Login failed: {exc.code} {detail}") from exc

    print("login_status:")
    for label, session in (
        ("admin", admin),
        ("student", student),
        ("counsellor", counsellor),
    ):
        print(
            f"  {label}: username={session['username']} role={session['role']} "
            f"password_reset_required={session.get('password_reset_required')}"
        )

    admin_token = str(admin["access_token"])
    student_token = str(student["access_token"])
    counsellor_token = str(counsellor["access_token"])

    student_overview = _request("/student/me/overview", token=student_token)
    faculty_summary = _request("/faculty/summary", token=counsellor_token)
    faculty_queue = _request("/faculty/priority-queue", token=counsellor_token)
    institution_overview = _request("/institution/risk-overview", token=admin_token)

    student_chat = _copilot_roundtrip(
        student_token,
        "Do I still have any uncleared I grade or R grade subjects?",
    )
    counsellor_chat = _copilot_roundtrip(
        counsellor_token,
        "Which of my students need weekly monitoring because of unresolved R grade burden?",
    )
    admin_chat = _copilot_roundtrip(
        admin_token,
        "Show prediction high risk and attendance risk semester wise and year wise.",
    )

    print("student_overview:")
    academic_progress = student_overview.get("academic_progress") or {}
    print(
        f"  student_id={student_overview.get('student_id')} "
        f"burden_count={academic_progress.get('active_burden_count')} "
        f"academic_risk_band={academic_progress.get('academic_risk_band')} "
        f"cadence={academic_progress.get('monitoring_cadence')}"
    )

    print("counsellor_summary:")
    print(
        f"  total_active_high_risk={faculty_summary.get('total_active_high_risk_students')} "
        f"active_burden={faculty_summary.get('total_students_with_active_academic_burden')} "
        f"active_r={faculty_summary.get('total_students_with_active_r_grade_burden')}"
    )

    print("counsellor_queue:")
    print(f"  total_students={faculty_queue.get('total_students')}")

    print("admin_overview:")
    print(
        f"  total_students={institution_overview.get('total_students')} "
        f"active_high_risk={institution_overview.get('total_high_risk_students')}"
    )

    print("student_chat:")
    print(student_chat)
    print("counsellor_chat:")
    print(counsellor_chat)
    print("admin_chat:")
    print(admin_chat)


if __name__ == "__main__":
    main()
