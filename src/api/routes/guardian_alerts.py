from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.alerts.guardian_alert_service import (
    build_guardian_escalation_assessment,
    queue_guardian_escalation_if_eligible,
)
from src.api.auth import AuthContext, require_roles
from src.api.schemas import (
    GuardianAlertEventItem,
    GuardianAlertHistoryResponse,
    GuardianAlertQueueResponse,
    GuardianEscalationEvaluationResponse,
)
from src.api.time_utils import to_ist
from src.db.database import get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/guardian-alerts", tags=["guardian-alerts"])


def _build_evaluation_response(student_id: int, repository: EventRepository) -> GuardianEscalationEvaluationResponse:
    assessment = build_guardian_escalation_assessment(repository, student_id)
    return GuardianEscalationEvaluationResponse(
        student_id=assessment.student_id,
        should_send=assessment.should_send,
        alert_type=assessment.alert_type,
        reason=assessment.reason,
        channel=assessment.channel,
        severity=assessment.severity,
        recipient=assessment.recipient,
        guardian_name=assessment.guardian_name,
        guardian_relationship=assessment.guardian_relationship,
        guardian_contact_enabled=assessment.guardian_contact_enabled,
        repeat_high_risk_count=assessment.repeat_high_risk_count,
        high_risk_cycle_count=assessment.high_risk_cycle_count,
        has_relapsed_after_recovery=assessment.has_relapsed_after_recovery,
        has_relapsed_after_resolution=assessment.has_relapsed_after_resolution,
        is_critical_unattended_case=assessment.is_critical_unattended_case,
        latest_prediction_id=assessment.latest_prediction_id,
    )


def _build_guardian_alert_item(row) -> GuardianAlertEventItem:
    return GuardianAlertEventItem(
        id=int(row.id),
        student_id=int(row.student_id),
        prediction_history_id=int(row.prediction_history_id),
        alert_type=row.alert_type,
        risk_level=row.risk_level,
        final_risk_probability=float(row.final_risk_probability),
        guardian_name=row.guardian_name,
        guardian_relationship=row.guardian_relationship,
        recipient=row.recipient,
        channel=row.channel,
        delivery_status=row.delivery_status,
        provider_name=row.provider_name,
        provider_message_id=row.provider_message_id,
        retry_count=int(row.retry_count or 0),
        error_message=row.error_message,
        context_snapshot=row.context_snapshot,
        sent_at=to_ist(row.sent_at),
    )


@router.get("/evaluation/{student_id}", response_model=GuardianEscalationEvaluationResponse)
def get_guardian_escalation_evaluation(
    student_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> GuardianEscalationEvaluationResponse:
    repository = EventRepository(db)
    return _build_evaluation_response(student_id, repository)


@router.get("/history/{student_id}", response_model=GuardianAlertHistoryResponse)
def get_guardian_alert_history(
    student_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> GuardianAlertHistoryResponse:
    repository = EventRepository(db)
    rows = repository.get_guardian_alert_history_for_student(student_id)
    return GuardianAlertHistoryResponse(
        student_id=student_id,
        alerts=[_build_guardian_alert_item(row) for row in rows],
    )


@router.post("/queue/{student_id}", response_model=GuardianAlertQueueResponse)
def queue_guardian_escalation(
    student_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> GuardianAlertQueueResponse:
    repository = EventRepository(db)
    result = queue_guardian_escalation_if_eligible(
        repository,
        student_id=student_id,
        actor_role=auth.role,
        actor_subject=auth.subject,
    )
    evaluation = _build_evaluation_response(student_id, repository)

    if result.queued:
        return GuardianAlertQueueResponse(
            queued=True,
            deduplicated=False,
            message=result.message,
            evaluation=evaluation,
            alert=_build_guardian_alert_item(result.alert_event),
        )

    return GuardianAlertQueueResponse(
        queued=False,
        deduplicated=result.deduplicated,
        message=result.message,
        evaluation=evaluation,
        alert=_build_guardian_alert_item(result.alert_event) if result.alert_event is not None else None,
    )
