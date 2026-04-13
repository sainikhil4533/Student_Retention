from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.ai_assistance_context import build_live_case_context
from src.api.auth import AuthContext, require_roles
from src.api.prediction_history_serialization import build_prediction_history_item_from_row
from src.ai.assistant_service import generate_recovery_plan
from src.api.schemas import (
    AIRecoveryPlanResponse,
    StudentProfileResponse,
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
    )
