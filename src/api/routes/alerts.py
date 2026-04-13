from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.auth import AuthContext, require_roles
from src.api.schemas import AlertEventItem, AlertHistoryResponse
from src.api.time_utils import to_ist
from src.db.database import get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/history/{student_id}", response_model=AlertHistoryResponse)
def get_student_alert_history(
    student_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> AlertHistoryResponse:
    repository = EventRepository(db)
    alert_rows = repository.get_alert_history_for_student(student_id)

    return AlertHistoryResponse(
        student_id=student_id,
        alerts=[
            AlertEventItem(
                student_id=row.student_id,
                prediction_history_id=row.prediction_history_id,
                alert_type=row.alert_type,
                risk_level=row.risk_level,
                final_risk_probability=float(row.final_risk_probability),
                recipient=row.recipient,
                email_status=row.email_status,
                retry_count=int(row.retry_count or 0),
                error_message=row.error_message,
                sent_at=to_ist(row.sent_at),
            )
            for row in alert_rows
        ],
    )
