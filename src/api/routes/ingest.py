from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.auth import AuthContext, require_roles
from src.api.dependencies import prediction_service
from src.api.scoring_service import score_student_from_db
from src.api.schemas import (
    ERPIngestionRequest,
    ERPIngestionResponse,
    FinanceIngestionRequest,
    FinanceIngestionResponse,
    LMSIngestionRequest,
    LMSIngestionResponse,
)
from src.api.time_utils import to_ist
from src.db.database import get_db
from src.db.repository import EventRepository
from src.worker.job_queue import (
    enqueue_faculty_alert_email_job,
    enqueue_student_warning_email_job,
)


router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/lms", response_model=LMSIngestionResponse)
def ingest_lms_event(
    payload: LMSIngestionRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> LMSIngestionResponse:
    repository = EventRepository(db)
    event = payload.model_dump()
    existing = repository.find_matching_lms_event(event)
    if existing is None:
        repository.add_lms_event(event)
        duplicate_ignored = False
    else:
        duplicate_ignored = True
    return LMSIngestionResponse(
        status="duplicate_ignored" if duplicate_ignored else "accepted",
        source="lms",
        ingested_count=0 if duplicate_ignored else 1,
        duplicate_ignored=duplicate_ignored,
        auto_score_triggered=False,
    )


@router.post("/erp", response_model=ERPIngestionResponse)
def ingest_erp_event(
    payload: ERPIngestionRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> ERPIngestionResponse:
    repository = EventRepository(db)
    event = payload.model_dump()
    existing = repository.find_matching_erp_event(event)
    if existing is None:
        repository.add_erp_event(event)
        duplicate_ignored = False
    else:
        duplicate_ignored = True
    auto_score_triggered = False
    alert_triggered = False
    alert_type = None
    alert_status = None
    score_result: dict = {}

    if duplicate_ignored:
        print(f"[ingest.erp] duplicate_ignored student_id={payload.student_id}")
        return ERPIngestionResponse(
            status="duplicate_ignored",
            source="erp",
            ingested_count=0,
            duplicate_ignored=True,
            auto_score_triggered=False,
            student_warning_triggered=False,
            student_warning_type=None,
            student_warning_status=None,
            recovery_deadline=None,
            alert_triggered=False,
            alert_type=None,
            alert_status=None,
        )

    profile = repository.get_student_profile(payload.student_id)
    lms_events = repository.get_lms_events_for_student(payload.student_id)
    print(
        f"[ingest.erp] student_id={payload.student_id} "
        f"profile_exists={bool(profile)} lms_count={len(lms_events)}"
    )
    if profile and lms_events:
        score_result = score_student_from_db(
            student_id=payload.student_id,
            db=db,
            prediction_service=prediction_service,
        )
        auto_score_triggered = True
        alert_triggered = bool(score_result.get("alert_triggered", False))
        alert_type = score_result.get("alert_type")
        alert_status = score_result.get("alert_status")
        if (
            score_result.get("student_warning_triggered")
            and score_result.get("student_warning_status") == "pending"
            and score_result.get("student_warning_event_id") is not None
        ):
            enqueue_student_warning_email_job(
                warning_event_id=int(score_result["student_warning_event_id"]),
                student_id=payload.student_id,
                prediction_history_id=int(score_result["prediction_history_id"]),
                warning_type=str(score_result["student_warning_type"]),
                recipient=str(profile.student_email or "unconfigured"),
            )
        if (
            alert_triggered
            and alert_status == "pending"
            and score_result.get("alert_event_id") is not None
        ):
            enqueue_faculty_alert_email_job(
                alert_event_id=int(score_result["alert_event_id"]),
                student_id=payload.student_id,
                prediction_history_id=int(score_result["prediction_history_id"]),
                alert_type=str(alert_type),
            )
        print(f"[ingest.erp] auto_score_triggered student_id={payload.student_id}")
    else:
        print(f"[ingest.erp] auto_score_skipped student_id={payload.student_id}")

    return ERPIngestionResponse(
        status="accepted",
        source="erp",
        ingested_count=1,
        duplicate_ignored=False,
        auto_score_triggered=auto_score_triggered,
        student_warning_triggered=bool(score_result.get("student_warning_triggered", False)) if auto_score_triggered else False,
        student_warning_type=score_result.get("student_warning_type") if auto_score_triggered else None,
        student_warning_status=score_result.get("student_warning_status") if auto_score_triggered else None,
        recovery_deadline=to_ist(score_result.get("recovery_deadline")) if auto_score_triggered else None,
        alert_triggered=alert_triggered,
        alert_type=alert_type,
        alert_status=alert_status,
    )


@router.post("/finance", response_model=FinanceIngestionResponse)
def ingest_finance_event(
    payload: FinanceIngestionRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> FinanceIngestionResponse:
    repository = EventRepository(db)
    event = payload.model_dump()
    existing = repository.find_matching_finance_event(event)
    if existing is None:
        repository.add_finance_event(event)
        duplicate_ignored = False
    else:
        duplicate_ignored = True
    return FinanceIngestionResponse(
        status="duplicate_ignored" if duplicate_ignored else "accepted",
        source="finance",
        ingested_count=0 if duplicate_ignored else 1,
        duplicate_ignored=duplicate_ignored,
        auto_score_triggered=False,
    )
