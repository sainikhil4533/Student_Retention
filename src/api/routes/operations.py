from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.auth import AuthContext, require_roles
from src.api.operational_context import (
    build_activity_summary,
    build_milestone_flags,
    build_sla_summary,
)
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
    )
