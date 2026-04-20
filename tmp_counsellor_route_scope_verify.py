from fastapi.testclient import TestClient

from src.api.auth import create_access_token
from src.api.main import app
from src.db.database import SessionLocal
from src.db.repository import EventRepository


def _ensure_profile(
    repository: EventRepository,
    *,
    student_id: int,
    counsellor_name: str,
    counsellor_email: str,
) -> None:
    repository.upsert_student_profile(
        {
            "student_id": student_id,
            "student_email": f"student{student_id}@college.edu",
            "faculty_name": "Faculty Mentor",
            "faculty_email": "faculty@college.edu",
            "counsellor_name": counsellor_name,
            "counsellor_email": counsellor_email,
            "parent_name": "Parent",
            "parent_relationship": "Father",
            "parent_email": f"parent{student_id}@mail.com",
            "parent_phone": "9000000000",
            "preferred_guardian_channel": "email",
            "guardian_contact_enabled": True,
            "external_student_ref": f"EXT-{student_id}",
            "profile_context": {
                "registration": {"final_status": "Studying"},
                "branch": "CSE",
                "region": "AP",
                "category": "General",
                "income": "Middle",
            },
            "gender": "M",
            "highest_education": "Intermediate",
            "age_band": "18-21",
            "disability_status": "N",
            "num_previous_attempts": 0.0,
        }
    )


def main() -> None:
    db = SessionLocal()
    try:
        repository = EventRepository(db)
        _ensure_profile(
            repository,
            student_id=90101,
            counsellor_name="Counsellor Scope",
            counsellor_email="scope.counsellor@college.edu",
        )
        _ensure_profile(
            repository,
            student_id=90102,
            counsellor_name="Other Counsellor",
            counsellor_email="other.counsellor@college.edu",
        )
    finally:
        db.close()

    client = TestClient(app)

    counsellor_token = create_access_token(
        role="counsellor",
        subject="scope.counsellor",
        display_name="Counsellor Scope",
    )
    admin_token = create_access_token(
        role="admin",
        subject="admin.scope",
        display_name="Admin Scope",
    )
    student_token = create_access_token(
        role="student",
        subject="student.90101",
        student_id=90101,
        display_name="Student 90101",
    )

    counsellor_headers = {"Authorization": f"Bearer {counsellor_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    student_headers = {"Authorization": f"Bearer {student_token}"}

    in_scope_profile = client.get("/profiles/90101", headers=counsellor_headers)
    assert in_scope_profile.status_code == 200, in_scope_profile.text

    out_scope_profile = client.get("/profiles/90102", headers=counsellor_headers)
    assert out_scope_profile.status_code == 403, out_scope_profile.text

    in_scope_warning_history = client.get("/warnings/history/90101", headers=counsellor_headers)
    assert in_scope_warning_history.status_code == 200, in_scope_warning_history.text

    out_scope_warning_history = client.get("/warnings/history/90102", headers=counsellor_headers)
    assert out_scope_warning_history.status_code == 403, out_scope_warning_history.text

    out_scope_alert_history = client.get("/alerts/history/90102", headers=counsellor_headers)
    assert out_scope_alert_history.status_code == 403, out_scope_alert_history.text

    out_scope_guardian_history = client.get("/guardian-alerts/history/90102", headers=counsellor_headers)
    assert out_scope_guardian_history.status_code == 403, out_scope_guardian_history.text

    out_scope_timeline = client.get("/timeline/90102", headers=counsellor_headers)
    assert out_scope_timeline.status_code == 403, out_scope_timeline.text

    in_scope_timeline = client.get("/timeline/90101", headers=counsellor_headers)
    assert in_scope_timeline.status_code == 200, in_scope_timeline.text

    out_scope_case_state = client.get("/cases/state/90102", headers=counsellor_headers)
    assert out_scope_case_state.status_code == 403, out_scope_case_state.text

    in_scope_case_state = client.get("/cases/state/90101", headers=counsellor_headers)
    assert in_scope_case_state.status_code == 404, in_scope_case_state.text

    admin_profile = client.get("/profiles/90102", headers=admin_headers)
    assert admin_profile.status_code == 200, admin_profile.text

    student_self_profile = client.get("/profiles/90101", headers=student_headers)
    assert student_self_profile.status_code == 200, student_self_profile.text

    student_other_profile = client.get("/profiles/90102", headers=student_headers)
    assert student_other_profile.status_code == 403, student_other_profile.text

    print("Counsellor route scope verification passed.")


if __name__ == "__main__":
    main()
