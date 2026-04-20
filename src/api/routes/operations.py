from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.auth import AuthContext, require_roles
from src.api.academic_burden import build_academic_burden_summary
from src.api.operational_context import (
    build_activity_summary,
    build_milestone_flags,
    build_sla_summary,
)
from src.api.scope import ensure_student_scope_access
from src.api.schemas import (
    ActivitySummary,
    MilestoneFlagsSummary,
    SLASummary,
    StudentOperationalContextResponse,
)
from src.api.time_utils import to_ist
from src.db.database import get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/context/{student_id}", response_model=StudentOperationalContextResponse)
def get_student_operational_context(
    student_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> StudentOperationalContextResponse:
    repository = EventRepository(db)
    ensure_student_scope_access(auth=auth, repository=repository, student_id=student_id)
    prediction_history = repository.get_prediction_history_for_student(student_id)
    latest_prediction = prediction_history[0] if prediction_history else None
    profile = repository.get_student_profile(student_id)
    lms_events = repository.get_lms_events_for_student(student_id)
    erp_event = repository.get_latest_erp_event(student_id)
    finance_event = repository.get_latest_finance_event(student_id)
    warning_history = repository.get_student_warning_history_for_student(student_id)
    latest_warning = warning_history[0] if warning_history else None
    alert_history = repository.get_alert_history_for_student(student_id)
    latest_alert = alert_history[0] if alert_history else None
    intervention_history = repository.get_intervention_history_for_student(student_id)
    academic_progress = repository.get_student_academic_progress_record(student_id)
    semester_progress = repository.get_latest_student_semester_progress_record(student_id)
    subject_rows = repository.get_current_student_subject_attendance_records(student_id)
    academic_rows = repository.get_current_student_academic_records(student_id)
    all_subject_rows = repository.get_student_subject_attendance_records(student_id)
    all_academic_rows = repository.get_student_academic_records(student_id)

    if latest_prediction is None:
        raise HTTPException(status_code=404, detail="No prediction history found for student.")
    if profile is None:
        raise HTTPException(status_code=404, detail="Student profile not found.")

    activity_summary = build_activity_summary(
        lms_events=lms_events,
        erp_event=erp_event,
        finance_event=finance_event,
    )
    milestone_flags = build_milestone_flags(
        profile=profile,
        erp_event=erp_event,
        finance_event=finance_event,
    )
    sla_summary = build_sla_summary(
        latest_prediction=latest_prediction,
        latest_warning=latest_warning,
        latest_alert=latest_alert,
        intervention_history=intervention_history,
    )

    weakest_subject = next(
        (row for row in subject_rows if row.subject_attendance_percent is not None),
        None,
    )
    current_cgpa = next(
        (
            float(row.cgpa)
            for row in academic_rows
            if getattr(row, "cgpa", None) is not None
        ),
        None,
    )
    current_backlogs = next(
        (
            int(float(row.backlogs))
            for row in academic_rows
            if getattr(row, "backlogs", None) is not None
        ),
        None,
    )
    academic_burden = build_academic_burden_summary(
        academic_rows=all_academic_rows,
        attendance_rows=all_subject_rows,
    )
    academic_context = {
        "institution_name": getattr(academic_progress, "institution_name", None),
        "branch": getattr(academic_progress, "branch", None),
        "current_year": getattr(academic_progress, "current_year", None),
        "current_semester": getattr(academic_progress, "current_semester", None),
        "semester_mode": getattr(academic_progress, "semester_mode", None),
        "current_academic_status": getattr(academic_progress, "current_academic_status", None),
        "standing_label": getattr(academic_progress, "standing_label", None),
        "overall_attendance_percent": (
            float(semester_progress.overall_attendance_percent)
            if semester_progress is not None and semester_progress.overall_attendance_percent is not None
            else None
        ),
        "overall_status": getattr(semester_progress, "overall_status", None),
        "subjects_below_75_count": int(getattr(semester_progress, "subjects_below_75_count", 0) or 0),
        "subjects_below_65_count": int(getattr(semester_progress, "subjects_below_65_count", 0) or 0),
        "has_i_grade_risk": bool(getattr(semester_progress, "has_i_grade_risk", False)),
        "has_r_grade_risk": bool(getattr(semester_progress, "has_r_grade_risk", False)),
        "current_eligibility": getattr(semester_progress, "current_eligibility", None),
        "academic_risk_band": academic_burden["academic_risk_band"],
        "active_burden_count": int(academic_burden["active_burden_count"]),
        "has_active_i_grade_burden": bool(academic_burden["has_active_i_grade_burden"]),
        "has_active_r_grade_burden": bool(academic_burden["has_active_r_grade_burden"]),
        "monitoring_cadence": academic_burden["monitoring_cadence"],
        "academic_burden_summary": academic_burden["summary"],
        "active_i_grade_subjects": academic_burden["active_i_grade_subjects"],
        "active_r_grade_subjects": academic_burden["active_r_grade_subjects"],
        "weakest_subject_name": getattr(weakest_subject, "subject_name", None),
        "weakest_subject_percent": (
            float(weakest_subject.subject_attendance_percent)
            if weakest_subject is not None and weakest_subject.subject_attendance_percent is not None
            else None
        ),
        "weakest_subject_status": getattr(weakest_subject, "subject_status", None),
        "cgpa": current_cgpa,
        "backlogs": current_backlogs if current_backlogs is not None else getattr(academic_progress, "total_backlogs", None),
        "subject_risk_summary": [
            {
                "subject_name": str(row.subject_name),
                "subject_attendance_percent": (
                    float(row.subject_attendance_percent)
                    if row.subject_attendance_percent is not None
                    else None
                ),
                "subject_status": row.subject_status,
                "grade_consequence": row.grade_consequence,
            }
            for row in subject_rows[:5]
        ],
    }

    return StudentOperationalContextResponse(
        student_id=student_id,
        risk_level=(
            "HIGH" if int(latest_prediction.final_predicted_class) == 1 else "LOW"
        ),
        final_risk_probability=float(latest_prediction.final_risk_probability),
        activity_summary=ActivitySummary(
            last_meaningful_activity_at=to_ist(
                activity_summary["last_meaningful_activity_at"]
            ),
            last_meaningful_activity_source=activity_summary["last_meaningful_activity_source"],
            days_since_last_meaningful_activity=activity_summary[
                "days_since_last_meaningful_activity"
            ],
            latest_lms_event_day=activity_summary["latest_lms_event_day"],
            summary=activity_summary["summary"],
        ),
        milestone_flags=MilestoneFlagsSummary(**milestone_flags),
        sla_summary=SLASummary(**sla_summary),
        academic_context=academic_context,
    )
