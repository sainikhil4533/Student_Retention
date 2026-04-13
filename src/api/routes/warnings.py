from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.auth import AuthContext, require_same_student_or_roles
from src.api.schemas import StudentWarningEventItem, StudentWarningHistoryResponse
from src.api.time_utils import to_ist
from src.db.database import get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/warnings", tags=["warnings"])


@router.get("/history/{student_id}", response_model=StudentWarningHistoryResponse)
def get_student_warning_history(
    student_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_same_student_or_roles("counsellor", "admin", "system")),
) -> StudentWarningHistoryResponse:
    repository = EventRepository(db)
    warning_rows = repository.get_student_warning_history_for_student(student_id)

    return StudentWarningHistoryResponse(
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
    )
