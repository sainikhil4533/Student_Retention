from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.auth import AuthContext, require_roles
from src.api.schemas import (
    RecommendedActionItem,
    RiskDriverItem,
    RiskDriverResponse,
    StabilitySummary,
    TriggerAlertItem,
    TriggerAlertSummary,
    RiskTrendSummary,
    RiskTypeSummary,
)
from src.api.student_intelligence import build_current_student_intelligence
from src.db.database import get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.get("/{student_id}", response_model=RiskDriverResponse)
def get_risk_drivers(
    student_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> RiskDriverResponse:
    repository = EventRepository(db)
    latest_prediction = repository.get_latest_prediction_for_student(student_id)
    prediction_rows = repository.get_prediction_history_for_student(student_id)
    lms_events = repository.get_lms_events_for_student(student_id)
    erp_event = repository.get_latest_erp_event(student_id)

    if latest_prediction is None:
        raise HTTPException(status_code=404, detail="No prediction history found for student.")
    if not lms_events:
        raise HTTPException(status_code=404, detail="No LMS events found for student.")
    if erp_event is None:
        raise HTTPException(status_code=404, detail="No ERP event found for student.")

    risk_level = "HIGH" if int(latest_prediction.final_predicted_class) == 1 else "LOW"
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

    return RiskDriverResponse(
        student_id=student_id,
        risk_level=risk_level,
        final_risk_probability=float(latest_prediction.final_risk_probability),
        risk_trend=RiskTrendSummary(**intelligence["risk_trend"]),
        stability=StabilitySummary(**intelligence["stability"]),
        risk_type=RiskTypeSummary(**intelligence["risk_type"]),
        recommended_actions=[
            RecommendedActionItem(**item)
            for item in intelligence["recommended_actions"]
        ],
        trigger_alerts=TriggerAlertSummary(
            triggers=[TriggerAlertItem(**item) for item in intelligence["trigger_alerts"]["triggers"]],
            has_critical_trigger=bool(intelligence["trigger_alerts"]["has_critical_trigger"]),
            trigger_count=int(intelligence["trigger_alerts"]["trigger_count"]),
            summary=str(intelligence["trigger_alerts"]["summary"]),
        ),
        drivers=[RiskDriverItem(**driver) for driver in intelligence["drivers"]],
    )
