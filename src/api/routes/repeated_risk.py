from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.auth import AuthContext, require_roles
from src.api.schemas import RepeatedRiskReportResponse, RepeatedRiskResponse
from src.api.time_utils import to_ist
from src.db.database import get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/risk-patterns", tags=["risk-patterns"])


def _build_repeated_risk_response(student_id: int, history, intervention_history) -> RepeatedRiskResponse:
    ordered = list(reversed(history))
    total_predictions = len(ordered)
    high_risk_prediction_count = sum(
        1 for row in ordered if int(row.final_predicted_class) == 1
    )
    resolution_times = sorted(
        row.created_at
        for row in intervention_history
        if str(row.action_status).strip().lower() == "resolved" and row.created_at is not None
    )

    high_risk_cycle_count = 0
    previous_was_high = False
    has_relapsed_after_recovery = False
    has_relapsed_after_resolution = False
    has_seen_recovery = False

    for row in ordered:
        is_high = int(row.final_predicted_class) == 1
        if is_high and not previous_was_high:
            high_risk_cycle_count += 1
            if has_seen_recovery:
                has_relapsed_after_recovery = True
            if any(resolution_time < row.created_at for resolution_time in resolution_times):
                has_relapsed_after_resolution = True
        if not is_high:
            has_seen_recovery = True
        previous_was_high = is_high

    latest = history[0]
    currently_high_risk = int(latest.final_predicted_class) == 1
    is_repeated_risk_case = high_risk_cycle_count >= 2 or high_risk_prediction_count >= 2
    is_reopened_case = currently_high_risk and has_relapsed_after_resolution

    if is_reopened_case:
        summary = "Student became high risk again after faculty had already marked the case resolved."
    elif has_relapsed_after_recovery:
        summary = "Student became high risk again after at least one recovery period."
    elif is_repeated_risk_case:
        summary = "Student has repeated high-risk predictions and should be monitored more closely."
    elif currently_high_risk:
        summary = "Student is currently high risk, but no repeated-risk cycle has been detected yet."
    else:
        summary = "Student does not currently show a repeated high-risk pattern."

    return RepeatedRiskResponse(
        student_id=student_id,
        total_predictions=total_predictions,
        high_risk_prediction_count=high_risk_prediction_count,
        high_risk_cycle_count=high_risk_cycle_count,
        currently_high_risk=currently_high_risk,
        is_repeated_risk_case=is_repeated_risk_case,
        has_relapsed_after_recovery=has_relapsed_after_recovery,
        has_relapsed_after_resolution=has_relapsed_after_resolution,
        is_reopened_case=is_reopened_case,
        latest_prediction_created_at=to_ist(latest.created_at),
        summary=summary,
    )


@router.get("/repeated", response_model=RepeatedRiskReportResponse)
def get_repeated_risk_report(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> RepeatedRiskReportResponse:
    repository = EventRepository(db)
    latest_predictions = repository.get_latest_predictions_for_all_students()
    repeated_risk_students: list[RepeatedRiskResponse] = []

    for prediction in latest_predictions:
        student_id = int(prediction.student_id)
        history = repository.get_prediction_history_for_student(student_id)
        intervention_history = repository.get_intervention_history_for_student(student_id)
        if not history:
            continue

        response = _build_repeated_risk_response(
            student_id=student_id,
            history=history,
            intervention_history=intervention_history,
        )
        if (
            response.is_repeated_risk_case
            or response.has_relapsed_after_recovery
            or response.has_relapsed_after_resolution
        ):
            repeated_risk_students.append(response)

    repeated_risk_students.sort(
        key=lambda item: (
            item.is_reopened_case,
            item.has_relapsed_after_resolution,
            item.has_relapsed_after_recovery,
            item.high_risk_cycle_count,
            item.high_risk_prediction_count,
            item.currently_high_risk,
        ),
        reverse=True,
    )

    return RepeatedRiskReportResponse(
        total_students=len(repeated_risk_students),
        students=repeated_risk_students,
    )


@router.get("/repeated/{student_id}", response_model=RepeatedRiskResponse)
def get_repeated_risk_analysis(
    student_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> RepeatedRiskResponse:
    repository = EventRepository(db)
    history = repository.get_prediction_history_for_student(student_id)
    intervention_history = repository.get_intervention_history_for_student(student_id)

    if not history:
        raise HTTPException(status_code=404, detail="No prediction history found for student.")
    return _build_repeated_risk_response(
        student_id=student_id,
        history=history,
        intervention_history=intervention_history,
    )
