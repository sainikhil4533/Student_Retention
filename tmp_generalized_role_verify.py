from types import SimpleNamespace

from src.api.copilot_intents import detect_copilot_intent
from src.api.copilot_tools import _build_academic_scope_summary


class _FakeRepository:
    def get_student_academic_progress_records_for_students(self, student_ids=None):
        return [
            SimpleNamespace(student_id=1, branch="CSE"),
            SimpleNamespace(student_id=2, branch="CSE"),
            SimpleNamespace(student_id=3, branch="ECE"),
        ]

    def get_latest_student_semester_progress_records_for_students(self, student_ids=None):
        return [
            SimpleNamespace(student_id=1, overall_status="SAFE", has_i_grade_risk=True, has_r_grade_risk=False),
            SimpleNamespace(student_id=2, overall_status="SHORTAGE", has_i_grade_risk=False, has_r_grade_risk=True),
            SimpleNamespace(student_id=3, overall_status="SHORTAGE", has_i_grade_risk=True, has_r_grade_risk=False),
        ]

    def get_current_student_subject_attendance_records_for_students(self, student_ids=None):
        return [
            SimpleNamespace(student_id=1, subject_name="DBMS", subject_attendance_percent=71.0, subject_status="I_GRADE"),
            SimpleNamespace(student_id=1, subject_name="JAVA", subject_attendance_percent=82.0, subject_status="SAFE"),
            SimpleNamespace(student_id=2, subject_name="DBMS", subject_attendance_percent=61.0, subject_status="R_GRADE"),
            SimpleNamespace(student_id=2, subject_name="OS", subject_attendance_percent=69.0, subject_status="I_GRADE"),
            SimpleNamespace(student_id=3, subject_name="Signals", subject_attendance_percent=73.0, subject_status="I_GRADE"),
        ]


def main() -> None:
    assert detect_copilot_intent(role="counsellor", message="which students have i grade risk") == "cohort_summary"
    assert detect_copilot_intent(role="counsellor", message="which subjects are causing most attendance issues") == "cohort_summary"
    assert detect_copilot_intent(role="admin", message="which branch needs attention first") in {"cohort_summary", "admin_governance"}
    assert detect_copilot_intent(role="admin", message="how many students have r grade risk") == "cohort_summary"

    summary = _build_academic_scope_summary(repository=_FakeRepository())
    assert summary["total_students_with_overall_shortage"] == 2
    assert summary["total_students_with_i_grade_risk"] == 2
    assert summary["total_students_with_r_grade_risk"] == 1
    assert summary["top_subjects"][0]["subject_name"] == "DBMS"
    assert summary["ranked_branches"][0]["branch"] == "CSE"

    print("Generalized counsellor/admin verification passed.")


if __name__ == "__main__":
    main()
