from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.ai_assistance_context import build_live_case_context
from src.api.academic_burden import build_academic_burden_summary
from src.api.auth import AuthContext, require_roles
from src.api.prediction_history_serialization import build_prediction_history_item_from_row
from src.ai.assistant_service import generate_recovery_plan
from src.api.schemas import (
    AIRecoveryPlanResponse,
    StudentAcademicProgressSummary,
    StudentSemesterProgressItem,
    StudentProfileResponse,
    StudentSubjectAttendanceItem,
    StudentSelfOverviewResponse,
    StudentWarningEventItem,
    StudentWarningHistoryResponse,
)
from src.api.student_intelligence import build_current_student_intelligence
from src.api.time_utils import to_ist
from src.db.database import get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/student", tags=["student"])


@router.get("/me/overview", response_model=StudentSelfOverviewResponse)
def get_student_self_overview(
    auth: AuthContext = Depends(require_roles("student")),
    db: Session = Depends(get_db),
) -> StudentSelfOverviewResponse:
    if auth.student_id is None:
        raise HTTPException(status_code=400, detail="Student token is missing student binding.")

    student_id = auth.student_id
    repository = EventRepository(db)
    profile = repository.get_student_profile(student_id)
    latest_prediction = repository.get_latest_prediction_for_student(student_id)
    prediction_rows = repository.get_prediction_history_for_student(student_id)
    warning_rows = repository.get_student_warning_history_for_student(student_id)
    lms_events = repository.get_lms_events_for_student(student_id)
    erp_event = repository.get_latest_erp_event(student_id)
    academic_progress_row = repository.get_student_academic_progress_record(student_id)
    current_subject_attendance = repository.get_current_student_subject_attendance_records(student_id)
    semester_progress_rows = repository.get_student_semester_progress_records(student_id)
    all_academic_rows = repository.get_student_academic_records(student_id)
    all_attendance_rows = repository.get_student_subject_attendance_records(student_id)

    if profile is None:
        raise HTTPException(status_code=404, detail="Student profile not found.")
    if latest_prediction is None:
        raise HTTPException(status_code=404, detail="No prediction history found for student.")

    intelligence = None
    if lms_events and erp_event is not None:
        intelligence = build_current_student_intelligence(
            prediction_rows=prediction_rows,
            latest_prediction=latest_prediction,
            lms_events=lms_events,
            erp_event=erp_event,
            erp_history=repository.get_erp_event_history_for_student(student_id),
            finance_event=repository.get_latest_finance_event(student_id),
            finance_history=repository.get_finance_event_history_for_student(student_id),
            previous_prediction=prediction_rows[1] if len(prediction_rows) >= 2 else None,
        )

    recovery_plan = AIRecoveryPlanResponse(
        **generate_recovery_plan(build_live_case_context(repository=repository, student_id=student_id))
    )
    current_semester_progress = next(
        (
            row
            for row in semester_progress_rows
            if academic_progress_row is not None
            and academic_progress_row.current_semester is not None
            and row.semester == academic_progress_row.current_semester
        ),
        semester_progress_rows[-1] if semester_progress_rows else None,
    )
    weakest_subject = next(
        (
            row
            for row in current_subject_attendance
            if row.subject_attendance_percent is not None
        ),
        None,
    )
    attendance_summary = _build_student_attendance_summary(
        current_semester_progress=current_semester_progress,
        current_subject_attendance=current_subject_attendance,
        weakest_subject=weakest_subject,
    )
    academic_burden = build_academic_burden_summary(
        academic_rows=all_academic_rows,
        attendance_rows=all_attendance_rows,
    )

    return StudentSelfOverviewResponse(
        student_id=student_id,
        profile=StudentProfileResponse(
            student_id=profile.student_id,
            student_email=profile.student_email,
            faculty_name=profile.faculty_name,
            faculty_email=profile.faculty_email,
            counsellor_name=getattr(profile, "counsellor_name", None),
            counsellor_email=getattr(profile, "counsellor_email", None),
            parent_name=profile.parent_name,
            parent_relationship=profile.parent_relationship,
            parent_email=profile.parent_email,
            parent_phone=profile.parent_phone,
            preferred_guardian_channel=profile.preferred_guardian_channel,
            guardian_contact_enabled=bool(profile.guardian_contact_enabled),
            external_student_ref=getattr(profile, "external_student_ref", None),
            profile_context=getattr(profile, "profile_context", None),
            gender=profile.gender,
            highest_education=profile.highest_education,
            age_band=profile.age_band,
            disability_status=profile.disability_status,
            num_previous_attempts=float(profile.num_previous_attempts),
        ),
        latest_prediction=build_prediction_history_item_from_row(
            latest_prediction,
            intelligence,
        ),
        warning_history=StudentWarningHistoryResponse(
            student_id=student_id,
            warnings=[
                StudentWarningEventItem(
                    student_id=row.student_id,
                    prediction_history_id=row.prediction_history_id,
                    warning_type=row.warning_type,
                    risk_level=row.risk_level,
                    final_risk_probability=float(row.final_risk_probability),
                    recipient=row.recipient,
                    delivery_status=row.delivery_status,
                    retry_count=int(row.retry_count or 0),
                    error_message=row.error_message,
                    sent_at=to_ist(row.sent_at),
                    recovery_deadline=to_ist(row.recovery_deadline),
                    resolved_at=to_ist(row.resolved_at),
                    resolution_status=row.resolution_status,
                )
                for row in warning_rows
            ],
        ),
        recovery_plan=recovery_plan,
        academic_progress=StudentAcademicProgressSummary(
            institution_name=_profile_context_text(profile, "institution_name"),
            branch=_profile_context_text(profile, "branch"),
            batch=_profile_context_text(profile, "batch"),
            current_year=getattr(academic_progress_row, "current_year", None),
            current_semester=getattr(academic_progress_row, "current_semester", None),
            current_academic_status=getattr(academic_progress_row, "current_academic_status", None),
            semester_mode=getattr(academic_progress_row, "semester_mode", None),
            expected_graduation_year=getattr(academic_progress_row, "expected_graduation_year", None),
            standing_label=getattr(academic_progress_row, "standing_label", None),
            total_backlogs=getattr(academic_progress_row, "total_backlogs", None),
            current_overall_attendance_percent=getattr(current_semester_progress, "overall_attendance_percent", None),
            current_overall_status=getattr(current_semester_progress, "overall_status", None),
            current_subjects_below_75_count=int(getattr(current_semester_progress, "subjects_below_75_count", 0) or 0),
            current_subjects_below_65_count=int(getattr(current_semester_progress, "subjects_below_65_count", 0) or 0),
            has_i_grade_risk=bool(getattr(current_semester_progress, "has_i_grade_risk", False)),
            has_r_grade_risk=bool(getattr(current_semester_progress, "has_r_grade_risk", False)),
            weakest_subject_name=getattr(weakest_subject, "subject_name", None),
            weakest_subject_percent=getattr(weakest_subject, "subject_attendance_percent", None),
            academic_risk_band=academic_burden["academic_risk_band"],
            active_burden_count=int(academic_burden["active_burden_count"]),
            has_active_i_grade_burden=bool(academic_burden["has_active_i_grade_burden"]),
            has_active_r_grade_burden=bool(academic_burden["has_active_r_grade_burden"]),
            monitoring_cadence=academic_burden["monitoring_cadence"],
            academic_burden_summary=academic_burden["summary"],
            active_i_grade_subjects=academic_burden["active_i_grade_subjects"],
            active_r_grade_subjects=academic_burden["active_r_grade_subjects"],
            attendance_summary=attendance_summary,
            subject_attendance=[
                StudentSubjectAttendanceItem(
                    year=row.year,
                    semester=row.semester,
                    subject_code=row.subject_code,
                    subject_name=row.subject_name,
                    subject_type=row.subject_type,
                    overall_attendance_percent=row.overall_attendance_percent,
                    subject_attendance_percent=row.subject_attendance_percent,
                    required_percent=row.required_percent,
                    overall_status=row.overall_status,
                    subject_status=row.subject_status,
                    grade_consequence=row.grade_consequence,
                    condonation_required=bool(row.condonation_required),
                    summer_repeat_required=bool(row.summer_repeat_required),
                    internals_repeat_required=bool(row.internals_repeat_required),
                    end_sem_eligible=bool(row.end_sem_eligible),
                    classes_conducted=row.classes_conducted,
                    classes_attended=row.classes_attended,
                    consecutive_absences=row.consecutive_absences,
                    missed_days=row.missed_days,
                    trend=row.trend,
                )
                for row in current_subject_attendance
            ],
            semester_progress=[
                StudentSemesterProgressItem(
                    year=row.year,
                    semester=row.semester,
                    overall_attendance_percent=row.overall_attendance_percent,
                    overall_status=row.overall_status,
                    subjects_below_75_count=row.subjects_below_75_count,
                    subjects_below_65_count=row.subjects_below_65_count,
                    has_i_grade_risk=bool(row.has_i_grade_risk),
                    has_r_grade_risk=bool(row.has_r_grade_risk),
                    current_eligibility=row.current_eligibility,
                    semester_mode=row.semester_mode,
                )
                for row in semester_progress_rows
            ],
        ),
    )


def _profile_context_text(profile, key: str) -> str | None:
    context = getattr(profile, "profile_context", None) or {}
    value = context.get(key)
    if value in (None, ""):
        return None
    return str(value)


def _build_student_attendance_summary(
    *,
    current_semester_progress,
    current_subject_attendance,
    weakest_subject,
) -> str:
    if current_semester_progress is None and not current_subject_attendance:
        return "Attendance details are not available yet for the current student record."

    overall_percent = getattr(current_semester_progress, "overall_attendance_percent", None)
    overall_status = getattr(current_semester_progress, "overall_status", None)
    parts: list[str] = []
    if overall_percent is not None:
        parts.append(f"Your current overall attendance is {overall_percent:.2f} percent")
        if overall_status:
            parts[-1] += f" and is marked as {str(overall_status).replace('_', ' ').title()}"
    if weakest_subject is not None:
        weakest_name = getattr(weakest_subject, "subject_name", "your weakest subject")
        weakest_percent = getattr(weakest_subject, "subject_attendance_percent", None)
        weakest_status = getattr(weakest_subject, "subject_status", None)
        if weakest_percent is not None:
            text = f"the weakest visible subject right now is {weakest_name} at {weakest_percent:.2f} percent"
            if weakest_status:
                text += f" with status {str(weakest_status).replace('_', ' ').title()}"
            parts.append(text)
    if not parts:
        return "Attendance records exist, but the current summary could not be derived clearly."
    return ". ".join(parts) + "."
