from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.api.auth import AuthContext
from src.api.copilot_planner import plan_copilot_query
from src.api.copilot_tools import generate_grounded_copilot_answer


class FakeCounsellorRepository:
    def __init__(self) -> None:
        self.db = None
        self._profiles = [
            SimpleNamespace(student_id=880001, branch="CSE", current_year=1, current_semester=1, gender="Male"),
            SimpleNamespace(student_id=880002, branch="CSE", current_year=2, current_semester=3, gender="Female"),
            SimpleNamespace(student_id=880003, branch="ECE", current_year=3, current_semester=5, gender="Male"),
            SimpleNamespace(student_id=880004, branch="CSE", current_year=4, current_semester=7, gender="Female"),
            SimpleNamespace(student_id=880005, branch="EEE", current_year=4, current_semester=7, gender="Male"),
            SimpleNamespace(student_id=880006, branch="CSE", current_year=2, current_semester=4, gender="Female"),
        ]
        self._progress = [
            SimpleNamespace(student_id=880001, year=1, semester=1, overall_status="SAFE", has_i_grade_risk=False, has_r_grade_risk=False, overall_attendance_percent=85.4),
            SimpleNamespace(student_id=880002, year=2, semester=3, overall_status="SHORTAGE", has_i_grade_risk=True, has_r_grade_risk=False, overall_attendance_percent=72.2),
            SimpleNamespace(student_id=880003, year=3, semester=5, overall_status="SAFE", has_i_grade_risk=False, has_r_grade_risk=False, overall_attendance_percent=82.0),
            SimpleNamespace(student_id=880004, year=4, semester=7, overall_status="SHORTAGE", has_i_grade_risk=True, has_r_grade_risk=True, overall_attendance_percent=63.0),
            SimpleNamespace(student_id=880005, year=4, semester=7, overall_status="SHORTAGE", has_i_grade_risk=False, has_r_grade_risk=True, overall_attendance_percent=61.5),
            SimpleNamespace(student_id=880006, year=2, semester=4, overall_status="SAFE", has_i_grade_risk=True, has_r_grade_risk=False, overall_attendance_percent=75.2),
        ]
        self._subjects = [
            SimpleNamespace(student_id=880002, subject_name="Big Data Analytics", subject_attendance_percent=69.0, subject_status="I_GRADE"),
            SimpleNamespace(student_id=880004, subject_name="Big Data Analytics", subject_attendance_percent=61.0, subject_status="R_GRADE"),
            SimpleNamespace(student_id=880005, subject_name="Power Systems", subject_attendance_percent=60.0, subject_status="R_GRADE"),
            SimpleNamespace(student_id=880006, subject_name="DBMS", subject_attendance_percent=74.0, subject_status="I_GRADE"),
        ]
        self._predictions = [
            SimpleNamespace(student_id=880001, final_predicted_class=1, final_risk_probability=0.5976),
            SimpleNamespace(student_id=880002, final_predicted_class=1, final_risk_probability=0.8121),
            SimpleNamespace(student_id=880003, final_predicted_class=0, final_risk_probability=0.3220),
            SimpleNamespace(student_id=880004, final_predicted_class=1, final_risk_probability=0.9011),
            SimpleNamespace(student_id=880005, final_predicted_class=1, final_risk_probability=0.8734),
            SimpleNamespace(student_id=880006, final_predicted_class=1, final_risk_probability=0.7412),
        ]

    def get_imported_student_profiles_for_counsellor_identity(self, subject: str, display_name: str | None):
        return list(self._profiles)

    def get_imported_student_profiles(self):
        return list(self._profiles)

    def get_student_academic_progress_records_for_students(self, student_ids=None):
        rows = [
            SimpleNamespace(
                student_id=row.student_id,
                branch=next((profile.branch for profile in self._profiles if int(profile.student_id) == int(row.student_id)), "Unknown"),
                current_year=row.year,
                current_semester=row.semester,
                semester_mode="regular_coursework",
            )
            for row in self._progress
        ]
        if student_ids is None:
            return rows
        wanted = {int(value) for value in student_ids}
        return [row for row in rows if int(row.student_id) in wanted]

    def get_latest_student_semester_progress_records_for_students(self, student_ids=None):
        if student_ids is None:
            return list(self._progress)
        wanted = {int(value) for value in student_ids}
        return [row for row in self._progress if int(row.student_id) in wanted]

    def get_current_student_subject_attendance_records_for_students(self, student_ids=None):
        if student_ids is None:
            return list(self._subjects)
        wanted = {int(value) for value in student_ids}
        return [row for row in self._subjects if int(row.student_id) in wanted]

    def get_latest_predictions_for_all_students(self):
        return list(self._predictions)


def _plan_and_answer(message: str) -> str:
    repo = FakeCounsellorRepository()
    auth = AuthContext(role="counsellor", subject="scope.counsellor", display_name="Scope Counsellor")
    plan = plan_copilot_query(
        role="counsellor",
        message=message,
        session_messages=[],
        profiles=repo.get_imported_student_profiles_for_counsellor_identity(subject=auth.subject, display_name=auth.display_name),
    )
    with patch("src.api.copilot_tools.get_faculty_priority_queue") as mock_queue, patch(
        "src.api.copilot_tools.get_faculty_summary"
    ) as mock_summary, patch(
        "src.api.copilot_tools._build_active_burden_scope_summary"
    ) as mock_burden:
        mock_queue.return_value = SimpleNamespace(
            total_students=4,
            queue=[
                SimpleNamespace(student_id=880004, priority_label="HIGH", sla_status="WITHIN_MONITORING", final_risk_probability=0.9011, queue_reason="Repeated high risk"),
                SimpleNamespace(student_id=880005, priority_label="HIGH", sla_status="WITHIN_MONITORING", final_risk_probability=0.8734, queue_reason="R-grade burden"),
                SimpleNamespace(student_id=880002, priority_label="HIGH", sla_status="WITHIN_MONITORING", final_risk_probability=0.8121, queue_reason="Attendance shortage"),
            ],
        )
        mock_summary.return_value = SimpleNamespace()
        mock_burden.return_value = {
            "total_students_with_active_burden": 3,
            "total_students_with_active_i_grade_burden": 2,
            "total_students_with_active_r_grade_burden": 2,
            "students_requiring_weekly_monitoring": 2,
            "students_requiring_monthly_monitoring": 1,
            "top_students": [],
        }
        answer, *_ = generate_grounded_copilot_answer(
            auth=auth,
            repository=repo,
            message=message,
            session_messages=[],
            query_plan=plan.to_dict(),
        )
    return answer


def main() -> None:
    top_answer = _plan_and_answer("top 5 risky students")
    critical_answer = _plan_and_answer("give me most critical students")
    worst_answer = _plan_and_answer("who are worst performing")
    count_answer = _plan_and_answer("total risky students count")

    assert "top 5" in top_answer.lower()
    assert "most critical" in critical_answer.lower() or "critical" in critical_answer.lower()
    assert "performing worst" in worst_answer.lower() or "risk-and-pressure view" in worst_answer.lower()
    assert "there are" in count_answer.lower() and "high-risk" in count_answer.lower()
    assert top_answer != critical_answer != worst_answer

    help_answer = _plan_and_answer("how can I help them")
    intervention_answer = _plan_and_answer("what intervention should I take")
    reduce_answer = _plan_and_answer("how to reduce their risk")
    needed_answer = _plan_and_answer("what actions are needed")

    assert "support plan" in help_answer.lower()
    assert "intervention plan" in intervention_answer.lower()
    assert "risk-reduction plan" in reduce_answer.lower()
    assert "actions currently needed" in needed_answer.lower()
    assert len({help_answer, intervention_answer, reduce_answer, needed_answer}) == 4

    print("Counsellor fixture family verification passed.")


if __name__ == "__main__":
    main()
