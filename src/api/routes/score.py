from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.auth import AuthContext, require_roles, require_same_student_or_roles
from src.api.dependencies import prediction_service
from src.api.prediction_history_serialization import build_prediction_history_item_from_row
from src.api.scoring_service import score_student_from_db
from src.api.schemas import (
    PredictionHistoryItem,
    PredictionHistoryResponse,
    ScoreStudentRequest,
    ScoreStudentResponse,
)
from src.api.student_intelligence import build_current_student_intelligence
from src.api.time_utils import to_ist
from src.db.database import get_db
from src.db.repository import EventRepository
from src.worker.job_queue import (
    enqueue_faculty_alert_email_job,
    enqueue_student_warning_email_job,
)


router = APIRouter(prefix="/score", tags=["score"])


@router.post("/student", response_model=ScoreStudentResponse)
def score_student(
    payload: ScoreStudentRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> ScoreStudentResponse:
    try:
        repository = EventRepository(db)
        repository.upsert_student_profile(payload.demographics.model_dump())
        result = score_student_from_db(
            student_id=payload.demographics.student_id,
            db=db,
            prediction_service=prediction_service,
        )
        if (
            result.get("student_warning_triggered")
            and result.get("student_warning_status") == "pending"
            and result.get("student_warning_event_id") is not None
        ):
            enqueue_student_warning_email_job(
                warning_event_id=int(result["student_warning_event_id"]),
                student_id=payload.demographics.student_id,
                prediction_history_id=int(result["prediction_history_id"]),
                warning_type=str(result["student_warning_type"]),
                recipient=str(payload.demographics.student_email or "unconfigured"),
            )
        if (
            result.get("alert_triggered")
            and result.get("alert_status") == "pending"
            and result.get("alert_event_id") is not None
        ):
            enqueue_faculty_alert_email_job(
                alert_event_id=int(result["alert_event_id"]),
                student_id=payload.demographics.student_id,
                prediction_history_id=int(result["prediction_history_id"]),
                alert_type=str(result["alert_type"]),
            )
        result["recovery_deadline"] = to_ist(result.get("recovery_deadline"))
        return ScoreStudentResponse(**result)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/history/{student_id}", response_model=PredictionHistoryResponse)
def get_student_prediction_history(
    student_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_same_student_or_roles("counsellor", "admin", "system")),
) -> PredictionHistoryResponse:
    repository = EventRepository(db)
    history_rows = repository.get_prediction_history_for_student(student_id)
    lms_events = repository.get_lms_events_for_student(student_id)
    erp_event = repository.get_latest_erp_event(student_id)
    intelligence_by_prediction_id: dict[int, dict] = {}
    if lms_events and erp_event is not None:
        erp_history = repository.get_erp_event_history_for_student(student_id)
        finance_event = repository.get_latest_finance_event(student_id)
        finance_history = repository.get_finance_event_history_for_student(student_id)
        for index, row in enumerate(history_rows):
            intelligence_by_prediction_id[int(row.id)] = build_current_student_intelligence(
                prediction_rows=history_rows,
                latest_prediction=row,
                lms_events=lms_events,
                erp_event=erp_event,
                erp_history=erp_history,
                finance_event=finance_event,
                finance_history=finance_history,
                previous_prediction=history_rows[index + 1]
                if index + 1 < len(history_rows)
                else None,
            )

    return PredictionHistoryResponse(
        student_id=student_id,
        history=[
            build_prediction_history_item_from_row(
                row,
                intelligence_by_prediction_id.get(int(row.id)),
            )
            for row in history_rows
        ],
    )


@router.get("/latest/{student_id}", response_model=PredictionHistoryItem)
def get_latest_student_prediction(
    student_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_same_student_or_roles("counsellor", "admin", "system")),
) -> PredictionHistoryItem:
    repository = EventRepository(db)
    row = repository.get_latest_prediction_for_student(student_id)

    if not row:
        raise HTTPException(status_code=404, detail="No prediction history found for student.")

    prediction_rows = repository.get_prediction_history_for_student(student_id)
    lms_events = repository.get_lms_events_for_student(student_id)
    erp_event = repository.get_latest_erp_event(student_id)
    intelligence = None
    if lms_events and erp_event is not None:
        erp_history = repository.get_erp_event_history_for_student(student_id)
        finance_event = repository.get_latest_finance_event(student_id)
        finance_history = repository.get_finance_event_history_for_student(student_id)
        intelligence = build_current_student_intelligence(
            prediction_rows=prediction_rows,
            latest_prediction=row,
            lms_events=lms_events,
            erp_event=erp_event,
            erp_history=erp_history,
            finance_event=finance_event,
            finance_history=finance_history,
            previous_prediction=prediction_rows[1] if len(prediction_rows) >= 2 else None,
        )

    return build_prediction_history_item_from_row(row, intelligence)
