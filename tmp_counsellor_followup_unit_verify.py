from __future__ import annotations

from types import SimpleNamespace

from src.api.copilot_tools import (
    _build_counsellor_student_action_answer,
    _enrich_counsellor_memory_context,
)


def _verify_burden_monitoring_response_type() -> None:
    memory = _enrich_counsellor_memory_context(
        memory_context={"intent": "counsellor_active_burden_monitoring"},
        lowered="which of my students need weekly monitoring because of unresolved r grade burden",
    )
    assert memory.get("response_type") == "data"
    assert memory.get("last_topic") == "academic_burden_monitoring"


def _verify_student_action_progression() -> None:
    prediction = SimpleNamespace(
        recommended_actions=[
            {"title": "Schedule a focused academic review this week"},
            {"title": "Coordinate tutoring for weak coursework"},
        ]
    )
    semester_progress = SimpleNamespace(overall_status="SAFE")
    weakest_subject = SimpleNamespace(
        subject_name="Big Data Analytics",
        subject_attendance_percent=72.4,
    )
    latest_finance_event = SimpleNamespace(payment_status="overdue")
    latest_erp_event = SimpleNamespace(weighted_assessment_score=38.5)
    academic_burden = {
        "has_active_r_grade_burden": True,
        "has_active_i_grade_burden": False,
    }
    signal_bundle = {
        "latest_finance_event": latest_finance_event,
        "latest_erp_event": latest_erp_event,
    }

    first_answer, _tools, _limitations, first_memory = _build_counsellor_student_action_answer(
        student_id=880001,
        lowered="what action should i take for student 880001",
        prediction=prediction,
        semester_progress=semester_progress,
        subject_rows=[weakest_subject],
        academic_burden=academic_burden,
        signal_bundle=signal_bundle,
        active_warning=object(),
    )
    second_answer, _tools, _limitations, second_memory = _build_counsellor_student_action_answer(
        student_id=880001,
        lowered="continue",
        prediction=prediction,
        semester_progress=semester_progress,
        subject_rows=[weakest_subject],
        academic_burden=academic_burden,
        signal_bundle=signal_bundle,
        active_warning=object(),
    )

    first_lowered = first_answer.lower()
    second_lowered = second_answer.lower()

    assert "first grounded action plan" in first_lowered
    assert "first action" in first_lowered
    assert "next grounded follow-up plan" in second_lowered
    assert "weekly monitoring" in second_lowered
    assert "academic checkpoint" in second_lowered
    assert "attendance posture to keep protected" in second_lowered
    assert second_answer != first_answer

    assert first_memory.get("pending_role_follow_up") == "student_specific_action"
    assert second_memory.get("pending_role_follow_up") == "student_specific_action"
    assert first_memory.get("default_follow_up_rewrite") == "what action should i take for student 880001"
    assert second_memory.get("default_follow_up_rewrite") == "what action should i take for student 880001"


def main() -> None:
    _verify_burden_monitoring_response_type()
    _verify_student_action_progression()
    print("Counsellor follow-up unit verification passed.")


if __name__ == "__main__":
    main()
