from types import SimpleNamespace
from unittest.mock import patch

from src.api.auth import AuthContext
from src.api.copilot_tools import generate_grounded_copilot_answer
from src.api.routes import operations as operations_route


class FakeRepository:
    def __init__(self, _db=None) -> None:
        pass

    def get_prediction_history_for_student(self, student_id: int):
        return [SimpleNamespace(final_predicted_class=1, final_risk_probability=0.81, created_at=None)]

    def get_student_profile(self, student_id: int):
        return SimpleNamespace(student_email="student@example.edu", faculty_name="Dr Mentor", counsellor_name="Scope Counsellor")

    def get_lms_events_for_student(self, student_id: int):
        return []

    def get_latest_erp_event(self, student_id: int):
        return None

    def get_latest_finance_event(self, student_id: int):
        return None

    def get_student_warning_history_for_student(self, student_id: int):
        return []

    def get_alert_history_for_student(self, student_id: int):
        return []

    def get_intervention_history_for_student(self, student_id: int):
        return []

    def get_student_academic_progress_record(self, student_id: int):
        return SimpleNamespace(
            student_id=student_id,
            institution_name="Test University",
            branch="CSE",
            current_year=2,
            current_semester=3,
            semester_mode="regular_coursework",
            current_academic_status="Studying",
            standing_label="On Track",
            total_backlogs=1,
        )

    def get_latest_student_semester_progress_record(self, student_id: int):
        return SimpleNamespace(
            student_id=student_id,
            year=2,
            semester=3,
            overall_attendance_percent=72.5,
            overall_status="SHORTAGE",
            subjects_below_75_count=2,
            subjects_below_65_count=1,
            has_i_grade_risk=True,
            has_r_grade_risk=True,
            current_eligibility="Condonation needed",
        )

    def get_current_student_subject_attendance_records(self, student_id: int):
        return [
            SimpleNamespace(
                student_id=student_id,
                subject_name="DBMS",
                subject_attendance_percent=62.0,
                subject_status="R_GRADE",
                grade_consequence="Repeat Subject in Summer",
            ),
            SimpleNamespace(
                student_id=student_id,
                subject_name="JAVA",
                subject_attendance_percent=71.0,
                subject_status="I_GRADE",
                grade_consequence="Condonation + EndSem Only",
            ),
        ]

    def get_current_student_academic_records(self, student_id: int):
        return [SimpleNamespace(cgpa=7.4, backlogs=1)]

    def get_student_academic_progress_records_for_students(self, student_ids=None):
        rows = [self.get_student_academic_progress_record(880001)]
        if student_ids is None:
            return rows
        return [row for row in rows if 880001 in student_ids]

    def get_latest_student_semester_progress_records_for_students(self, student_ids=None):
        rows = [self.get_latest_student_semester_progress_record(880001)]
        if student_ids is None:
            return rows
        return [row for row in rows if 880001 in student_ids]

    def get_current_student_subject_attendance_records_for_students(self, student_ids=None):
        rows = self.get_current_student_subject_attendance_records(880001)
        if student_ids is None:
            return rows
        return rows if 880001 in student_ids else []

    def get_imported_student_profiles_for_counsellor_identity(self, subject: str, display_name: str | None):
        return [SimpleNamespace(student_id=880001)]

    def get_latest_prediction_for_student(self, student_id: int):
        return SimpleNamespace(final_risk_probability=0.81, final_predicted_class=1)

    def get_imported_student_profiles(self):
        return [SimpleNamespace(student_id=880001)]

    def get_latest_predictions_for_all_students(self):
        return [SimpleNamespace(student_id=880001, final_predicted_class=1, final_risk_probability=0.81)]

    def get_all_intervention_actions(self):
        return []

    def get_all_student_warning_events(self):
        return []


def verify_operations_context() -> None:
    with patch.object(operations_route, "EventRepository", FakeRepository), patch.object(
        operations_route, "ensure_student_scope_access", lambda auth, repository, student_id: None
    ), patch.object(
        operations_route, "build_activity_summary",
        lambda **kwargs: {
            "last_meaningful_activity_at": None,
            "last_meaningful_activity_source": None,
            "days_since_last_meaningful_activity": None,
            "latest_lms_event_day": None,
            "summary": "No recent LMS activity.",
        },
    ), patch.object(
        operations_route, "build_milestone_flags",
        lambda **kwargs: {
            "repeat_attempt_flag": False,
            "first_year_flag": False,
            "backlog_heavy_flag": False,
            "pre_exam_phase_flag": False,
            "fee_pressure_flag": False,
            "active_flags": ["attendance_shortage"],
            "summary": "Attendance shortage remains active.",
        },
    ), patch.object(
        operations_route, "build_sla_summary",
        lambda **kwargs: {
            "sla_status": "watch",
            "hours_since_latest_prediction": None,
            "hours_since_warning_created": None,
            "hours_to_first_faculty_action": None,
            "hours_open_without_faculty_action": None,
            "followup_overdue": False,
            "summary": "No overdue follow-up right now.",
        },
    ):
        response = operations_route.get_student_operational_context(
            student_id=880001,
            db=None,
            auth=AuthContext(role="admin", subject="admin.scope"),
        )
    assert response.academic_context is not None
    assert response.academic_context["branch"] == "CSE"
    assert response.academic_context["subjects_below_65_count"] == 1
    assert response.academic_context["weakest_subject_name"] == "DBMS"


def verify_copilot_drilldowns() -> None:
    repo = FakeRepository()
    counsellor_answer, *_ = generate_grounded_copilot_answer(
        auth=AuthContext(role="counsellor", subject="scope.counsellor", display_name="Scope Counsellor"),
        repository=repo,
        message="show details for student 880001",
        session_messages=[],
        query_plan={"primary_intent": "student_drilldown", "normalized_message": "show details for student 880001"},
    )
    admin_answer, *_ = generate_grounded_copilot_answer(
        auth=AuthContext(role="admin", subject="admin.scope"),
        repository=repo,
        message="show details for student 880001",
        session_messages=[],
        query_plan={"primary_intent": "student_drilldown", "normalized_message": "show details for student 880001"},
    )
    lowered_counsellor = counsellor_answer.lower()
    lowered_admin = admin_answer.lower()
    assert "overall attendance" in lowered_counsellor
    assert "current eligibility" in lowered_counsellor or "additional grounded details were condensed" in lowered_counsellor
    assert "overall attendance" in lowered_admin
    assert "weakest subject" in lowered_admin


def main() -> None:
    verify_operations_context()
    verify_copilot_drilldowns()
    print("Deep drilldown verification passed.")


if __name__ == "__main__":
    main()
