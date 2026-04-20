from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.api.auth import AuthContext
from src.api.copilot_memory import resolve_copilot_memory_context
from src.api.copilot_planner import plan_copilot_query
from src.api.copilot_tools import generate_grounded_copilot_answer


class FakeAdminRepository:
    def __init__(self) -> None:
        self.db = None
        self._profiles = [
            SimpleNamespace(student_id=880001, branch="CSE", current_year=1, current_semester=1, gender="Male", profile_context={"branch": "CSE", "gender": "Male"}),
            SimpleNamespace(student_id=880002, branch="CSE", current_year=2, current_semester=3, gender="Female", profile_context={"branch": "CSE", "gender": "Female"}),
            SimpleNamespace(student_id=880003, branch="ECE", current_year=1, current_semester=2, gender="Male", profile_context={"branch": "ECE", "gender": "Male"}),
            SimpleNamespace(student_id=880004, branch="ECE", current_year=4, current_semester=7, gender="Female", profile_context={"branch": "ECE", "gender": "Female"}),
            SimpleNamespace(student_id=880005, branch="EEE", current_year=3, current_semester=5, gender="Male", profile_context={"branch": "EEE", "gender": "Male"}),
            SimpleNamespace(student_id=880006, branch="EEE", current_year=4, current_semester=8, gender="Female", profile_context={"branch": "EEE", "gender": "Female"}),
        ]
        self._progress = [
            SimpleNamespace(student_id=880001, year=1, semester=1, overall_status="SAFE", has_i_grade_risk=False, has_r_grade_risk=False, overall_attendance_percent=84.0, current_year=1, current_semester=1),
            SimpleNamespace(student_id=880002, year=2, semester=3, overall_status="SHORTAGE", has_i_grade_risk=True, has_r_grade_risk=False, overall_attendance_percent=71.0, current_year=2, current_semester=3),
            SimpleNamespace(student_id=880003, year=1, semester=2, overall_status="SAFE", has_i_grade_risk=False, has_r_grade_risk=False, overall_attendance_percent=83.0, current_year=1, current_semester=2),
            SimpleNamespace(student_id=880004, year=4, semester=7, overall_status="SHORTAGE", has_i_grade_risk=True, has_r_grade_risk=True, overall_attendance_percent=62.0, current_year=4, current_semester=7),
            SimpleNamespace(student_id=880005, year=3, semester=5, overall_status="SAFE", has_i_grade_risk=False, has_r_grade_risk=False, overall_attendance_percent=80.0, current_year=3, current_semester=5),
            SimpleNamespace(student_id=880006, year=4, semester=8, overall_status="SHORTAGE", has_i_grade_risk=False, has_r_grade_risk=True, overall_attendance_percent=60.0, current_year=4, current_semester=8),
        ]
        self._subjects = [
            SimpleNamespace(student_id=880002, subject_name="Data Structures", subject_attendance_percent=70.0, subject_status="I_GRADE"),
            SimpleNamespace(student_id=880004, subject_name="VLSI Design", subject_attendance_percent=61.0, subject_status="R_GRADE"),
            SimpleNamespace(student_id=880006, subject_name="Power Electronics", subject_attendance_percent=60.0, subject_status="R_GRADE"),
        ]
        self._predictions = [
            SimpleNamespace(student_id=880001, final_predicted_class=1, final_risk_probability=0.66, finance_modifier=0.00),
            SimpleNamespace(student_id=880002, final_predicted_class=1, final_risk_probability=0.82, finance_modifier=0.12),
            SimpleNamespace(student_id=880003, final_predicted_class=0, final_risk_probability=0.31, finance_modifier=0.00),
            SimpleNamespace(student_id=880004, final_predicted_class=1, final_risk_probability=0.91, finance_modifier=0.18),
            SimpleNamespace(student_id=880005, final_predicted_class=1, final_risk_probability=0.73, finance_modifier=0.00),
            SimpleNamespace(student_id=880006, final_predicted_class=1, final_risk_probability=0.88, finance_modifier=0.22),
        ]

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
                profile_context=getattr(profile, "profile_context", {}),
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

    def get_latest_student_semester_progress_record(self, student_id: int):
        for row in self._progress:
            if int(row.student_id) == int(student_id):
                return row
        return None

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

    def get_all_intervention_actions(self):
        return []

    def get_all_student_warning_events(self):
        return []

    def get_all_prediction_history(self):
        rows = []
        for row in self._predictions:
            rows.append(
                SimpleNamespace(
                    student_id=row.student_id,
                    final_predicted_class=row.final_predicted_class,
                    final_risk_probability=row.final_risk_probability,
                    generated_at=None,
                )
            )
        return rows

    def get_active_student_warning_for_student(self, student_id: int):
        return None


class FixtureAdminClient:
    def __init__(self) -> None:
        self.repository = FakeAdminRepository()
        self.auth = AuthContext(role="admin", subject="admin.retention", display_name="Admin Retention")
        self.session_messages: list[object] = []

    def _signal_bundle(self, student_id: int) -> dict:
        lms_map = {
            880001: {"lms_clicks_7d": 120, "lms_unique_resources_7d": 12, "primary_type": "academic_decline"},
            880002: {"lms_clicks_7d": 38, "lms_unique_resources_7d": 3, "primary_type": "finance_driven"},
            880003: {"lms_clicks_7d": 110, "lms_unique_resources_7d": 10, "primary_type": "stable_profile"},
            880004: {"lms_clicks_7d": 46, "lms_unique_resources_7d": 4, "primary_type": "academic_decline"},
            880005: {"lms_clicks_7d": 98, "lms_unique_resources_7d": 11, "primary_type": "academic_decline"},
            880006: {"lms_clicks_7d": 32, "lms_unique_resources_7d": 3, "primary_type": "finance_driven"},
        }
        erp_map = {
            880001: SimpleNamespace(weighted_assessment_score=35.0, assessment_submission_rate=0.72),
            880002: SimpleNamespace(weighted_assessment_score=48.0, assessment_submission_rate=0.68),
            880003: SimpleNamespace(weighted_assessment_score=76.0, assessment_submission_rate=0.92),
            880004: SimpleNamespace(weighted_assessment_score=34.0, assessment_submission_rate=0.61),
            880005: SimpleNamespace(weighted_assessment_score=39.0, assessment_submission_rate=0.82),
            880006: SimpleNamespace(weighted_assessment_score=42.0, assessment_submission_rate=0.63),
        }
        finance_map = {
            880001: SimpleNamespace(payment_status="paid", fee_overdue_amount=0.0),
            880002: SimpleNamespace(payment_status="partial", fee_overdue_amount=12000.0),
            880003: SimpleNamespace(payment_status="paid", fee_overdue_amount=0.0),
            880004: SimpleNamespace(payment_status="overdue", fee_overdue_amount=18000.0),
            880005: SimpleNamespace(payment_status="paid", fee_overdue_amount=0.0),
            880006: SimpleNamespace(payment_status="overdue", fee_overdue_amount=22000.0),
        }
        lms = lms_map[int(student_id)]
        return {
            "latest_prediction": self.repository.get_latest_prediction_for_student(student_id),
            "prediction_history": self.repository.get_prediction_history_for_student(student_id),
            "lms_events": [SimpleNamespace()],
            "latest_erp_event": erp_map[int(student_id)],
            "erp_history": [],
            "latest_finance_event": finance_map[int(student_id)],
            "finance_history": [],
            "intelligence": {
                "risk_type": {"primary_type": lms["primary_type"]},
                "lms_summary": {
                    "lms_clicks_7d": lms["lms_clicks_7d"],
                    "lms_unique_resources_7d": lms["lms_unique_resources_7d"],
                },
            },
        }

    def send(self, prompt: str) -> tuple[str, dict]:
        memory = resolve_copilot_memory_context(message=prompt, session_messages=self.session_messages)
        plan = plan_copilot_query(
            role="admin",
            message=prompt,
            session_messages=self.session_messages,
            profiles=self.repository.get_imported_student_profiles(),
        )
        with patch("src.api.copilot_tools._load_student_signal_bundle") as mock_signal_bundle, patch(
            "src.api.copilot_tools.get_faculty_priority_queue"
        ) as mock_queue, patch(
            "src.api.copilot_tools.get_faculty_summary"
        ) as mock_summary, patch(
            "src.api.copilot_tools.get_intervention_effectiveness_analytics"
        ) as mock_effectiveness:
            mock_signal_bundle.side_effect = lambda repository, student_id: self._signal_bundle(student_id)
            mock_queue.return_value = SimpleNamespace(total_students=3, queue=[])
            mock_summary.return_value = SimpleNamespace()
            mock_effectiveness.return_value = SimpleNamespace()
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
    client = FixtureAdminClient()

    answer, _ = client.send("compare lms vs erp impact")
    assert "erp" in answer.lower() and "lms" in answer.lower()

    answer, _ = client.send("how finance is affecting risk")
    assert "finance" in answer.lower() and "risk" in answer.lower()

    answer, _ = client.send("which factor impacts performance most")
    assert "factor" in answer.lower() or "driver" in answer.lower() or "academic-performance" in answer.lower()

    answer, _ = client.send("hidden risk across departments")
    assert "hidden-risk" in answer.lower() or "hidden risk" in answer.lower()

    grouped_client = FixtureAdminClient()
    answer, _ = grouped_client.send("year wise performance")
    assert "year-wise breakdown" in answer.lower()
    grouped_client = FixtureAdminClient()
    answer, _ = grouped_client.send("risk by department")
    assert "branch-wise breakdown" in answer.lower()
    grouped_client = FixtureAdminClient()
    answer, _ = grouped_client.send("performance by branch")
    assert "branch-wise breakdown" in answer.lower()
    grouped_client = FixtureAdminClient()
    answer, _ = grouped_client.send("compare 1st year vs final year")
    assert "year-wise breakdown" in answer.lower()

    print("Admin fixture family verification passed.")


if __name__ == "__main__":
    main()
