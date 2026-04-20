from types import SimpleNamespace

from src.api.academic_pressure import build_academic_pressure_snapshot


class FakeRepository:
    def __init__(self) -> None:
        self.progress_rows = [
            SimpleNamespace(student_id=1, branch="CSE", current_year=2, current_semester=3, semester_mode="regular_coursework"),
            SimpleNamespace(student_id=2, branch="CSE", current_year=2, current_semester=4, semester_mode="regular_coursework"),
            SimpleNamespace(student_id=3, branch="ECE", current_year=4, current_semester=8, semester_mode="internship"),
        ]
        self.semester_rows = [
            SimpleNamespace(student_id=1, year=2, semester=3, overall_status="SHORTAGE", has_i_grade_risk=True, has_r_grade_risk=False, overall_attendance_percent=72.0, semester_mode="regular_coursework"),
            SimpleNamespace(student_id=2, year=2, semester=4, overall_status="SAFE", has_i_grade_risk=False, has_r_grade_risk=True, overall_attendance_percent=61.0, semester_mode="regular_coursework"),
            SimpleNamespace(student_id=3, year=4, semester=8, overall_status="SAFE", has_i_grade_risk=False, has_r_grade_risk=False, overall_attendance_percent=83.0, semester_mode="internship"),
        ]
        self.subject_rows = [
            SimpleNamespace(student_id=1, subject_name="DBMS", subject_attendance_percent=68.0, subject_status="I_GRADE"),
            SimpleNamespace(student_id=1, subject_name="JAVA", subject_attendance_percent=79.0, subject_status="SAFE"),
            SimpleNamespace(student_id=2, subject_name="OS", subject_attendance_percent=60.0, subject_status="R_GRADE"),
            SimpleNamespace(student_id=3, subject_name="Internship Review", subject_attendance_percent=83.0, subject_status="SAFE"),
        ]

    def get_student_academic_progress_records_for_students(self, student_ids=None):
        if student_ids is None:
            return list(self.progress_rows)
        return [row for row in self.progress_rows if int(row.student_id) in student_ids]

    def get_latest_student_semester_progress_records_for_students(self, student_ids=None):
        if student_ids is None:
            return list(self.semester_rows)
        return [row for row in self.semester_rows if int(row.student_id) in student_ids]

    def get_current_student_subject_attendance_records_for_students(self, student_ids=None):
        if student_ids is None:
            return list(self.subject_rows)
        return [row for row in self.subject_rows if int(row.student_id) in student_ids]


def main() -> None:
    snapshot = build_academic_pressure_snapshot(FakeRepository(), bucket_limit=5, subject_limit=5)
    assert snapshot["total_students"] == 3
    assert snapshot["total_students_with_overall_shortage"] == 1
    assert snapshot["total_students_with_i_grade_risk"] == 1
    assert snapshot["total_students_with_r_grade_risk"] == 1

    top_subject = snapshot["top_subjects"][0]
    assert top_subject["subject_name"] == "OS"
    assert top_subject["r_grade_students"] == 1

    top_branch = snapshot["branch_pressure"][0]
    assert top_branch["bucket_label"] == "CSE"
    assert top_branch["students_with_r_grade_risk"] == 1
    assert top_branch["students_with_i_grade_risk"] == 1

    labels = {item["bucket_label"] for item in snapshot["semester_pressure"]}
    assert "Year 2 Sem 3" in labels
    assert "Year 4 Sem 8 (internship)" in labels
    print("Generalized analytics verification passed.")


if __name__ == "__main__":
    main()
