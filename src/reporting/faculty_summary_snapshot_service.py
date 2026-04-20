from __future__ import annotations

from datetime import UTC, datetime

from src.api.auth import AuthContext
from src.api.routes.faculty import get_faculty_summary
from src.api.routes.institution import get_institution_risk_overview
from src.api.routes.interventions import get_intervention_effectiveness_analytics
from src.api.schemas import (
    FacultySummaryResponse,
    FacultySummarySnapshotItem,
    InstitutionRiskOverviewResponse,
    InterventionEffectivenessResponse,
)
from src.api.time_utils import to_ist
from src.db.repository import EventRepository
from src.reporting.faculty_summary_email_service import send_faculty_summary_email

_SYSTEM_AUTH = AuthContext(role="system", subject="system")


def create_faculty_summary_snapshot(db, snapshot_type: str) -> FacultySummarySnapshotItem:
    repository = EventRepository(db)
    summary = get_faculty_summary(db=db, auth=_SYSTEM_AUTH)
    institution_overview = get_institution_risk_overview(db=db, auth=_SYSTEM_AUTH)
    intervention_effectiveness = get_intervention_effectiveness_analytics(db=db, auth=_SYSTEM_AUTH)
    row = repository.add_faculty_summary_snapshot(
        {
            "snapshot_type": snapshot_type,
            "summary_payload": {
                "summary": summary.model_dump(mode="json"),
                "institution_overview": institution_overview.model_dump(mode="json"),
                "intervention_effectiveness": intervention_effectiveness.model_dump(
                    mode="json"
                ),
            },
        }
    )
    return FacultySummarySnapshotItem(
        id=row.id,
        snapshot_type=row.snapshot_type,
        email_delivery_status=row.email_delivery_status,
        email_error_message=row.email_error_message,
        emailed_at=to_ist(row.emailed_at),
        generated_at=to_ist(row.generated_at),
        summary=FacultySummaryResponse.model_validate(row.summary_payload["summary"]),
        institution_overview=InstitutionRiskOverviewResponse.model_validate(
            row.summary_payload["institution_overview"]
        ),
        intervention_effectiveness=InterventionEffectivenessResponse.model_validate(
            row.summary_payload["intervention_effectiveness"]
        ),
    )


def deliver_faculty_summary_snapshot_email(db, snapshot_id: int) -> FacultySummarySnapshotItem:
    repository = EventRepository(db)
    row = repository.get_faculty_summary_snapshot(snapshot_id)
    if row is None:
        raise ValueError("Faculty summary snapshot not found.")

    snapshot_item = serialize_faculty_summary_snapshot(row)
    email_result = send_faculty_summary_email(snapshot_item)
    updated = repository.update_faculty_summary_snapshot(
        snapshot_id,
        {
            "email_delivery_status": email_result["status"],
            "email_error_message": email_result["error_message"],
            "emailed_at": datetime.now(UTC),
        },
    )
    return serialize_faculty_summary_snapshot(updated)


def serialize_faculty_summary_snapshot(row) -> FacultySummarySnapshotItem:
    payload = row.summary_payload or {}
    summary_payload = payload.get("summary", payload)
    return FacultySummarySnapshotItem(
        id=row.id,
        snapshot_type=row.snapshot_type,
        email_delivery_status=row.email_delivery_status,
        email_error_message=row.email_error_message,
        emailed_at=to_ist(row.emailed_at),
        generated_at=to_ist(row.generated_at),
        summary=FacultySummaryResponse.model_validate(summary_payload),
        institution_overview=(
            InstitutionRiskOverviewResponse.model_validate(payload["institution_overview"])
            if payload.get("institution_overview") is not None
            else None
        ),
        intervention_effectiveness=(
            InterventionEffectivenessResponse.model_validate(
                payload["intervention_effectiveness"]
            )
            if payload.get("intervention_effectiveness") is not None
            else None
        ),
    )
