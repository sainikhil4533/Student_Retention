from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.auth import AuthContext, require_roles
from src.api.institutional_analytics import (
    build_institution_risk_overview,
    resolve_department_label,
    resolve_semester_label,
)
from src.api.schemas import (
    InstitutionBucketSummary,
    InstitutionHeatmapCell,
    InstitutionRiskOverviewResponse,
    OutcomeDistributionItem,
    RiskTypeDistributionItem,
)
from src.api.student_intelligence import build_current_student_intelligence
from src.api.time_utils import to_ist
from src.db.database import get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/institution", tags=["institution"])


@router.get("/risk-overview", response_model=InstitutionRiskOverviewResponse)
def get_institution_risk_overview(
    imported_only: bool = False,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> InstitutionRiskOverviewResponse:
    repository = EventRepository(db)
    latest_predictions = repository.get_latest_predictions_for_all_students()
    if imported_only:
        imported_student_ids = {
            int(profile.student_id) for profile in repository.get_imported_student_profiles()
        }
        latest_predictions = [
            prediction
            for prediction in latest_predictions
            if int(prediction.student_id) in imported_student_ids
        ]

    student_rows: list[dict] = []
    for prediction in latest_predictions:
        student_id = int(prediction.student_id)
        profile = repository.get_student_profile(student_id)
        latest_erp_event = repository.get_latest_erp_event(student_id)
        latest_finance_event = repository.get_latest_finance_event(student_id)
        intervention_history = repository.get_intervention_history_for_student(student_id)
        latest_intervention = intervention_history[0] if intervention_history else None
        alert_history = repository.get_alert_history_for_student(student_id)
        latest_alert = alert_history[0] if alert_history else None
        guardian_alert_history = repository.get_guardian_alert_history_for_student(student_id)
        latest_guardian_alert = guardian_alert_history[0] if guardian_alert_history else None
        lms_events = repository.get_lms_events_for_student(student_id)
        prediction_rows = repository.get_prediction_history_for_student(student_id)

        intelligence = None
        if lms_events and latest_erp_event is not None:
            intelligence = build_current_student_intelligence(
                prediction_rows=prediction_rows,
                latest_prediction=prediction,
                lms_events=lms_events,
                erp_event=latest_erp_event,
                erp_history=repository.get_erp_event_history_for_student(student_id),
                finance_event=latest_finance_event,
                finance_history=repository.get_finance_event_history_for_student(student_id),
                previous_prediction=prediction_rows[1]
                if len(prediction_rows) >= 2
                else None,
            )

        latest_intervention_status = (
            str(latest_intervention.action_status).strip().lower()
            if latest_intervention is not None
            else None
        )
        followup_overdue = bool(
            latest_alert is not None
            and latest_alert.alert_type == "faculty_followup_reminder"
            and latest_intervention_status
            not in {"seen", "acknowledged", "contacted", "support_provided", "resolved"}
        )

        student_rows.append(
            {
                "student_id": student_id,
                "department_label": resolve_department_label(profile, latest_erp_event),
                "semester_label": resolve_semester_label(latest_erp_event),
                "category_label": _resolve_profile_context_label(profile, "category", "unknown_category"),
                "region_label": _resolve_profile_context_label(profile, "region", "unknown_region"),
                "income_label": _resolve_profile_context_label(profile, "income", "unknown_income"),
                "risk_level": "HIGH"
                if int(prediction.final_predicted_class) == 1
                else "LOW",
                "final_risk_probability": float(prediction.final_risk_probability),
                "risk_type": (
                    str(intelligence["risk_type"]["primary_type"])
                    if intelligence is not None
                    else "unavailable"
                ),
                "has_critical_trigger": (
                    bool(intelligence["trigger_alerts"]["has_critical_trigger"])
                    if intelligence is not None
                    else False
                ),
                "followup_overdue": followup_overdue,
                "has_guardian_escalation": latest_guardian_alert is not None,
                "is_reopened_case": bool(
                    latest_alert is not None
                    and latest_alert.alert_type == "faculty_followup_reminder"
                    and int(prediction.final_predicted_class) == 1
                    and latest_intervention_status == "resolved"
                ),
                "is_repeated_risk_case": len(
                    [row for row in prediction_rows if int(row.final_predicted_class) == 1]
                )
                >= 2,
                "outcome_status": _resolve_outcome_status(profile),
            }
        )

    summary = build_institution_risk_overview(student_rows=student_rows)

    return InstitutionRiskOverviewResponse(
        generated_at=to_ist(summary["generated_at"]),
        total_students=int(summary["total_students"]),
        total_high_risk_students=int(summary["total_high_risk_students"]),
        total_critical_trigger_students=int(summary["total_critical_trigger_students"]),
        total_followup_overdue_students=int(summary["total_followup_overdue_students"]),
        total_guardian_escalation_students=int(summary["total_guardian_escalation_students"]),
        total_reopened_cases=int(summary["total_reopened_cases"]),
        total_repeated_risk_students=int(summary["total_repeated_risk_students"]),
        total_dropped_students=int(summary["total_dropped_students"]),
        total_studying_students=int(summary["total_studying_students"]),
        total_graduated_students=int(summary["total_graduated_students"]),
        department_buckets=[
            InstitutionBucketSummary(**item) for item in summary["department_buckets"]
        ],
        semester_buckets=[
            InstitutionBucketSummary(**item) for item in summary["semester_buckets"]
        ],
        category_buckets=[
            InstitutionBucketSummary(**item) for item in summary["category_buckets"]
        ],
        region_buckets=[
            InstitutionBucketSummary(**item) for item in summary["region_buckets"]
        ],
        income_buckets=[
            InstitutionBucketSummary(**item) for item in summary["income_buckets"]
        ],
        heatmap_cells=[
            InstitutionHeatmapCell(**item) for item in summary["heatmap_cells"]
        ],
        top_risk_types=[
            RiskTypeDistributionItem(**item) for item in summary["top_risk_types"]
        ],
        outcome_distribution=[
            OutcomeDistributionItem(**item) for item in summary["outcome_distribution"]
        ],
        summary=str(summary["summary"]),
    )


def _resolve_outcome_status(profile) -> str:
    if profile is None:
        return "unknown"
    profile_context = getattr(profile, "profile_context", None) or {}
    registration = profile_context.get("registration") or {}
    value = registration.get("final_status")
    if value in (None, ""):
        return "unknown"
    return str(value)


def _resolve_profile_context_label(profile, key: str, fallback: str) -> str:
    if profile is None:
        return fallback
    profile_context = getattr(profile, "profile_context", None) or {}
    value = profile_context.get(key)
    if value in (None, ""):
        return fallback
    return str(value)
