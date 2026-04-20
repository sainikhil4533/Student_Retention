from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

from src.api.auth import AuthContext
from src.api.copilot_memory import resolve_copilot_memory_context
from src.api.copilot_planner import plan_copilot_query
from src.api.copilot_tools import generate_grounded_copilot_answer


@dataclass
class _SessionRow:
    role: str
    metadata_json: dict


class FakeCounsellorRepository:
    def __init__(self) -> None:
        self.db = None
        self._profiles = [
            SimpleNamespace(student_id=880001, branch="CSE", current_year=1, current_semester=1, gender="Male", external_student_ref="STU001"),
            SimpleNamespace(student_id=880002, branch="CSE", current_year=2, current_semester=3, gender="Female", external_student_ref="STU002"),
            SimpleNamespace(student_id=880003, branch="ECE", current_year=3, current_semester=5, gender="Male", external_student_ref="STU003"),
            SimpleNamespace(student_id=880004, branch="CSE", current_year=4, current_semester=7, gender="Female", external_student_ref="STU004"),
            SimpleNamespace(student_id=880005, branch="EEE", current_year=4, current_semester=7, gender="Male", external_student_ref="STU005"),
            SimpleNamespace(student_id=880006, branch="CSE", current_year=3, current_semester=6, gender="Female", external_student_ref="STU006"),
        ]
        self._progress = [
            SimpleNamespace(student_id=880001, year=1, semester=1, overall_status="SAFE", has_i_grade_risk=False, has_r_grade_risk=False, overall_attendance_percent=85.4),
            SimpleNamespace(student_id=880002, year=2, semester=3, overall_status="SHORTAGE", has_i_grade_risk=True, has_r_grade_risk=False, overall_attendance_percent=72.2),
            SimpleNamespace(student_id=880003, year=3, semester=5, overall_status="SAFE", has_i_grade_risk=False, has_r_grade_risk=False, overall_attendance_percent=82.0),
            SimpleNamespace(student_id=880004, year=4, semester=7, overall_status="SHORTAGE", has_i_grade_risk=True, has_r_grade_risk=True, overall_attendance_percent=63.0),
            SimpleNamespace(student_id=880005, year=4, semester=7, overall_status="SHORTAGE", has_i_grade_risk=False, has_r_grade_risk=True, overall_attendance_percent=61.5),
            SimpleNamespace(student_id=880006, year=3, semester=6, overall_status="SAFE", has_i_grade_risk=True, has_r_grade_risk=False, overall_attendance_percent=76.4),
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
                student_id=profile.student_id,
                branch=profile.branch,
                current_year=profile.current_year,
                current_semester=profile.current_semester,
                semester_mode="regular_coursework",
                gender=profile.gender,
            )
            for profile in self._profiles
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

    def get_latest_prediction_for_student(self, student_id: int):
        for row in self._predictions:
            if int(row.student_id) == int(student_id):
                return row
        return None

    def get_prediction_history_for_student(self, student_id: int):
        latest = self.get_latest_prediction_for_student(student_id)
        return [latest] if latest is not None else []

    def get_student_warning_history_for_student(self, student_id: int):
        return []

    def get_alert_history_for_student(self, student_id: int):
        return []

    def get_intervention_history_for_student(self, student_id: int):
        return []

    def get_lms_events_for_student(self, student_id: int):
        return []

    def get_active_student_warning_for_student(self, student_id: int):
        return None

    def get_student_profile(self, student_id: int):
        profile = next(profile for profile in self._profiles if int(profile.student_id) == int(student_id))
        return SimpleNamespace(
            student_email=f"{profile.external_student_ref.lower()}@example.edu",
            faculty_name="Dr Mentor",
            counsellor_name="Scope Counsellor",
        )

    def get_latest_lms_event(self, student_id: int):
        clicks = {
            880001: 164,
            880002: 55,
            880003: 140,
            880004: 121,
            880005: 44,
            880006: 130,
        }[int(student_id)]
        return SimpleNamespace(clicks_last_7d=clicks)

    def get_latest_erp_event(self, student_id: int):
        scores = {
            880001: (0.0, 0.85),
            880002: (48.0, 0.62),
            880003: (73.0, 0.91),
            880004: (39.0, 0.58),
            880005: (41.0, 0.66),
            880006: (66.0, 0.71),
        }[int(student_id)]
        return SimpleNamespace(weighted_assessment_score=scores[0], assessment_submission_rate=scores[1])

    def get_latest_finance_event(self, student_id: int):
        statuses = {
            880001: "paid",
            880002: "partial",
            880003: "paid",
            880004: "overdue",
            880005: "overdue",
            880006: "paid",
        }[int(student_id)]
        return SimpleNamespace(payment_status=statuses)


class FixtureConversationClient:
    def __init__(self) -> None:
        self.repository = FakeCounsellorRepository()
        self.auth = AuthContext(role="counsellor", subject="scope.counsellor", display_name="Scope Counsellor")
        self.session_messages: list[object] = []

    def send(self, prompt: str) -> tuple[str, dict]:
        memory = resolve_copilot_memory_context(message=prompt, session_messages=self.session_messages)
        plan = plan_copilot_query(
            role="counsellor",
            message=prompt,
            session_messages=self.session_messages,
            profiles=self.repository.get_imported_student_profiles_for_counsellor_identity(
                subject=self.auth.subject,
                display_name=self.auth.display_name,
            ),
        )
        with patch("src.api.copilot_tools.get_faculty_priority_queue") as mock_queue, patch(
            "src.api.copilot_tools.get_faculty_summary"
        ) as mock_summary, patch(
            "src.api.copilot_tools._build_active_burden_scope_summary"
        ) as mock_burden, patch(
            "src.api.copilot_tools._load_student_signal_bundle"
        ) as mock_signal_bundle:
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
                "total_students_with_active_academic_burden": 3,
            }
            mock_signal_bundle.side_effect = lambda repository, student_id: {
                "latest_prediction": self.repository.get_latest_prediction_for_student(student_id),
                "prediction_history": self.repository.get_prediction_history_for_student(student_id),
                "latest_lms_event": self.repository.get_latest_lms_event(student_id),
                "lms_events": [],
                "latest_erp_event": self.repository.get_latest_erp_event(student_id),
                "erp_history": [],
                "latest_finance_event": self.repository.get_latest_finance_event(student_id),
                "finance_history": [],
                "warning_history": [],
                "alert_history": [],
                "intervention_history": [],
            }
            answer, _tools, _limitations, memory_context = generate_grounded_copilot_answer(
                auth=self.auth,
                repository=self.repository,
                message=prompt,
                session_messages=self.session_messages,
                memory=memory,
                query_plan=plan.to_dict(),
            )
        self.session_messages.append(SimpleNamespace(role="user", metadata_json={}))
        self.session_messages.append(SimpleNamespace(role="assistant", metadata_json={"memory_context": memory_context}))
        return answer, memory_context


def main() -> None:
    client = FixtureConversationClient()

    answer, _ = client.send("show my students high risk branch wise")
    assert "branch-wise breakdown" in answer.lower()
    answer, _ = client.send("show only CSE")
    assert "matching students" in answer.lower()
    answer, _ = client.send("what about top 5")
    assert "top 5" in answer.lower()
    answer, _ = client.send("continue")
    assert "grounded operational action list" in answer.lower() or "support plan" in answer.lower() or "intervention plan" in answer.lower()

    fresh_filter_client = FixtureConversationClient()
    answer, _ = fresh_filter_client.send("show only CSE students")
    assert "cse" in answer.lower()
    answer, _ = fresh_filter_client.send("only final year")
    assert "matching students" in answer.lower() or "final year" in answer.lower()
    answer, _ = fresh_filter_client.send("only high risk")
    assert "high-risk" in answer.lower() or "high risk" in answer.lower()

    natural_client = FixtureConversationClient()
    answer, _ = natural_client.send("who needs attention")
    assert "priority" in answer.lower() or "student_id" in answer.lower()
    answer, _ = natural_client.send("which students are struggling")
    assert "pressure" in answer.lower() or "student_id" in answer.lower()
    answer, _ = natural_client.send("who needs urgent help")
    assert "student_id" in answer.lower() or "priority" in answer.lower()

    analytical_client = FixtureConversationClient()
    answer, _ = analytical_client.send("which department has more risk")
    assert "most pressured" in answer.lower() or "branch" in answer.lower()
    answer, _ = analytical_client.send("are my students improving")
    assert "improvement-versus-pressure" in answer.lower() or "trend caution" in answer.lower()

    print("Counsellor fixture conversation verification passed.")


if __name__ == "__main__":
    main()
