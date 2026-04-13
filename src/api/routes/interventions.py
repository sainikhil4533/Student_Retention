from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.auth import AuthContext, require_roles
from src.api.intervention_analytics import build_intervention_effectiveness_summary
from src.api.schemas import (
    InterventionActionCreateRequest,
    InterventionActionItem,
    InterventionEffectivenessItem,
    InterventionEffectivenessResponse,
    InterventionHistoryResponse,
    InterventionOutcomeRequest,
    InterventionReviewRequest,
)
from src.api.time_utils import to_ist
from src.db.database import get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/interventions", tags=["interventions"])


def _serialize_intervention_action(row) -> InterventionActionItem:
    return InterventionActionItem(
        id=row.id,
        student_id=row.student_id,
        alert_event_id=row.alert_event_id,
        action_status=row.action_status,
        actor_name=row.actor_name,
        notes=row.notes,
        alert_validity=row.alert_validity,
        false_alert_reason=row.false_alert_reason,
        reviewed_by=row.reviewed_by,
        reviewed_at=to_ist(row.reviewed_at),
        outcome_status=row.outcome_status,
        outcome_notes=row.outcome_notes,
        outcome_recorded_by=row.outcome_recorded_by,
        outcome_recorded_at=to_ist(row.outcome_recorded_at),
        created_at=to_ist(row.created_at),
    )


@router.post("/action", response_model=InterventionActionItem)
def create_intervention_action(
    payload: InterventionActionCreateRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> InterventionActionItem:
    repository = EventRepository(db)
    row = repository.add_intervention_action(payload.model_dump())
    return _serialize_intervention_action(row)


@router.post("/review", response_model=InterventionActionItem)
def review_intervention_action(
    payload: InterventionReviewRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> InterventionActionItem:
    repository = EventRepository(db)
    row = repository.update_intervention_action(
        payload.intervention_id,
        {
            "alert_validity": payload.alert_validity,
            "false_alert_reason": payload.false_alert_reason,
            "reviewed_by": payload.reviewed_by,
            "reviewed_at": datetime.now(UTC),
        },
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Intervention action not found.")
    return _serialize_intervention_action(row)


@router.post("/outcome", response_model=InterventionActionItem)
def record_intervention_outcome(
    payload: InterventionOutcomeRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> InterventionActionItem:
    repository = EventRepository(db)
    row = repository.update_intervention_action(
        payload.intervention_id,
        {
            "outcome_status": payload.outcome_status,
            "outcome_notes": payload.outcome_notes,
            "outcome_recorded_by": payload.outcome_recorded_by,
            "outcome_recorded_at": datetime.now(UTC),
        },
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Intervention action not found.")
    return _serialize_intervention_action(row)


@router.get("/history/{student_id}", response_model=InterventionHistoryResponse)
def get_intervention_history(
    student_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> InterventionHistoryResponse:
    repository = EventRepository(db)
    rows = repository.get_intervention_history_for_student(student_id)
    return InterventionHistoryResponse(
        student_id=student_id,
        interventions=[_serialize_intervention_action(row) for row in rows],
    )


@router.get("/analytics/effectiveness", response_model=InterventionEffectivenessResponse)
def get_intervention_effectiveness_analytics(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> InterventionEffectivenessResponse:
    repository = EventRepository(db)
    summary = build_intervention_effectiveness_summary(
        repository.get_all_intervention_actions()
    )
    return InterventionEffectivenessResponse(
        total_actions=int(summary["total_actions"]),
        total_reviewed_actions=int(summary["total_reviewed_actions"]),
        total_false_alerts=int(summary["total_false_alerts"]),
        total_valid_alerts=int(summary["total_valid_alerts"]),
        total_outcomes_recorded=int(summary["total_outcomes_recorded"]),
        total_improved_cases=int(summary["total_improved_cases"]),
        total_unresolved_cases=int(summary["total_unresolved_cases"]),
        review_coverage_percent=float(summary["review_coverage_percent"]),
        improvement_rate_percent=float(summary["improvement_rate_percent"]),
        false_alert_rate_percent=float(summary["false_alert_rate_percent"]),
        summary=str(summary["summary"]),
        action_effectiveness=[
            InterventionEffectivenessItem(**item)
            for item in summary["action_effectiveness"]
        ],
    )
