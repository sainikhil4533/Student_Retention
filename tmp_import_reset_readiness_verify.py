from __future__ import annotations

from io import BytesIO
import csv
import zipfile

from fastapi.testclient import TestClient

from src.api.main import app
from src.db.database import SessionLocal
from src.db.models import StudentProfile


def _login_admin(client: TestClient) -> str:
    response = client.post(
        "/auth/login",
        json={"username": "admin_demo", "password": "admin_demo"},
    )
    response.raise_for_status()
    payload = response.json()
    token = payload.get("access_token")
    assert token, "Admin login did not return an access token."
    return str(token)


def _build_minimal_vignan_zip() -> bytes:
    from io import StringIO

    sheets: dict[str, tuple[list[str], list[list[object]]]] = {
        "Admissions": (
            [
                "registerno",
                "Branch",
                "Batch",
                "Category",
                "Region",
                "ParentEdu",
                "Occupation",
                "Income",
                "Gender",
                "AgeBand",
                "Attempts",
            ],
            [["VR-TEST-001", "CSE", "2026", "OBC", "Urban", "Degree", "Employee", "Mid", "M", "18-20", 1]],
        ),
        "Academics": (
            ["registerno", "Semester", "CGPA", "Backlogs", "shortname", "Marks"],
            [["VR-TEST-001", 1, 7.8, 0, "MATHS", 82]],
        ),
        "Attendance": (
            [
                "registerno",
                "Semester",
                "Overall%",
                "shortname",
                "Subject%",
                "ConsecutiveAbs",
                "MissedvDays",
                "Trend",
            ],
            [["VR-TEST-001", 1, 88, "MATHS", 90, 0, 0, "Good"]],
        ),
        "Finance": (
            ["registerno", "Status", "Due", "DelayDays", "Scholarship", "Modifier"],
            [["VR-TEST-001", "paid", 0, 0, "None", 1.0]],
        ),
        "Registration": (
            ["registerno", "Semester", "Registered", "FinalStatus"],
            [["VR-TEST-001", 1, "Yes", "Studying"]],
        ),
        "LMS": (
            [
                "registerno",
                "event_date",
                "id_site",
                "sum_click",
                "engagement_tag",
                "resource_type",
            ],
            [["VR-TEST-001", "2026-04-13", "SITE-1", 14, "engaged", "video"]],
        ),
        "SupportMapping": (
            [
                "registerno",
                "student_email",
                "disability_status",
                "faculty_name",
                "faculty_email",
                "parent_name",
                "parent_relationship",
                "parent_email",
                "parent_phone",
                "preferred_guardian_channel",
                "guardian_contact_enabled",
                "counsellor_name",
                "counsellor_email",
            ],
            [[
                "VR-TEST-001",
                "vr-test-001@college.edu",
                "N",
                "Faculty Demo",
                "faculty.demo@college.edu",
                "Parent Demo",
                "Father",
                "parent.demo@example.com",
                "9999999999",
                "email",
                "true",
                "Counsellor Demo",
                "counsellor.demo@college.edu",
            ]],
        ),
    }

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for sheet_name, (headers, rows) in sheets.items():
            sio = StringIO()
            writer = csv.writer(sio, lineterminator="\n")
            writer.writerow(headers)
            for row in rows:
                writer.writerow(row)
            archive.writestr(f"{sheet_name}.csv", sio.getvalue().encode("utf-8"))
    return buffer.getvalue()


def _assert_import_cleanup_state() -> list[str]:
    failures: list[str] = []
    with SessionLocal() as db:
        imported_profiles = (
            db.query(StudentProfile)
            .filter(StudentProfile.external_student_ref.is_not(None))
            .count()
        )
        if imported_profiles != 0:
            failures.append(
                f"Database cleanup sanity check: expected 0 imported student_profiles, found {imported_profiles}."
            )
    return failures


def main() -> None:
    failures = _assert_import_cleanup_state()
    client = TestClient(app)
    token = _login_admin(client)
    headers = {"Authorization": f"Bearer {token}"}

    coverage_response = client.get("/reports/import-coverage", headers=headers)
    coverage_response.raise_for_status()
    coverage = coverage_response.json()
    if coverage.get("total_imported_students") != 0:
        failures.append(
            "Import coverage sanity check: expected total_imported_students = 0 after cleanup."
        )
    if coverage.get("scored_students") != 0:
        failures.append(
            "Import coverage sanity check: expected scored_students = 0 after cleanup."
        )
    if coverage.get("students"):
        failures.append(
            "Import coverage sanity check: expected no imported student rows after cleanup."
        )

    overview_response = client.get(
        "/institution/risk-overview?imported_only=true",
        headers=headers,
    )
    overview_response.raise_for_status()
    overview = overview_response.json()
    if overview.get("total_students") != 0:
        failures.append(
            "Institution imported_only sanity check: expected total_students = 0 after cleanup."
        )
    if overview.get("total_high_risk_students") != 0:
        failures.append(
            "Institution imported_only sanity check: expected total_high_risk_students = 0 after cleanup."
        )

    export_response = client.get(
        "/reports/exports/outcome-distribution?imported_only=true",
        headers=headers,
    )
    export_response.raise_for_status()
    export_text = export_response.text.strip().splitlines()
    if not export_text or export_text[0].strip() != "outcome_status,student_count":
        failures.append(
            "Outcome distribution export sanity check: expected CSV header to remain available."
        )

    invalid_zip = BytesIO()
    with zipfile.ZipFile(invalid_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Admissions.csv", "registerno,Branch\nVR-TEST-001,CSE\n")
    invalid_response = client.post(
        "/admin/imports/vignan?dry_run=true&trigger_scoring=false",
        headers=headers,
        files={"file": ("invalid_vignan.zip", invalid_zip.getvalue(), "application/zip")},
    )
    if invalid_response.status_code != 400:
        failures.append(
            "Upload readiness check: malformed dry-run upload should return 400 validation error."
        )

    payload = _build_minimal_vignan_zip()
    dry_run_response = client.post(
        "/admin/imports/vignan?dry_run=true&trigger_scoring=false",
        headers=headers,
        files={"file": ("minimal_vignan.zip", payload, "application/zip")},
    )
    dry_run_response.raise_for_status()
    dry_run = dry_run_response.json()
    if dry_run.get("status") != "completed":
        failures.append("Dry-run import readiness check: expected status `completed`.")
    if dry_run.get("total_students") != 1:
        failures.append("Dry-run import readiness check: expected total_students = 1.")
    if dry_run.get("profiles_upserted") != 1:
        failures.append("Dry-run import readiness check: expected profiles_upserted = 1.")
    if dry_run.get("scoring_triggered") != 0:
        failures.append(
            "Dry-run import readiness check: expected scoring_triggered = 0 when trigger_scoring=false."
        )
    if dry_run.get("errors"):
        failures.append(
            f"Dry-run import readiness check: expected no errors, got {dry_run.get('errors')}."
        )

    post_dry_run_coverage_response = client.get("/reports/import-coverage", headers=headers)
    post_dry_run_coverage_response.raise_for_status()
    post_dry_run_coverage = post_dry_run_coverage_response.json()
    if post_dry_run_coverage.get("total_imported_students") != 0:
        failures.append(
            "Dry-run no-persistence check: expected total_imported_students to remain 0 after dry run."
        )

    failures.extend(_assert_import_cleanup_state())

    if failures:
        print("Import reset / readiness verification failed:")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("Import cleanup sanity check passed.")
    print("Fresh admin upload dry-run readiness check passed.")


if __name__ == "__main__":
    main()
