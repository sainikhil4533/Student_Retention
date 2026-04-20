from src.api.copilot_intents import detect_copilot_intent
from src.api.routes.student import _build_student_attendance_summary


class DummySemesterProgress:
    overall_attendance_percent = 72.5
    overall_status = "SHORTAGE"


class DummyAttendanceRow:
    subject_name = "Database Management Systems"
    subject_attendance_percent = 62.0
    subject_status = "R_GRADE"


def main() -> None:
    assert detect_copilot_intent(role="student", message="what is my attendance right now") == "student_self_attendance"
    assert detect_copilot_intent(role="student", message="which data do you have of me") == "student_self_attendance"
    assert detect_copilot_intent(role="student", message="do i have r grade risk") == "student_self_subject_risk"
    assert detect_copilot_intent(role="student", message="can you plan my next few weeks") == "student_self_plan"

    summary = _build_student_attendance_summary(
        current_semester_progress=DummySemesterProgress(),
        current_subject_attendance=[DummyAttendanceRow()],
        weakest_subject=DummyAttendanceRow(),
    )
    assert "72.50 percent" in summary
    assert "Database Management Systems" in summary
    assert "R Grade" in summary or "R_GRADE" in summary

    print("Generalized student verification passed.")


if __name__ == "__main__":
    main()
