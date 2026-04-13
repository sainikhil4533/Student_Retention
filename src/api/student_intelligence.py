from __future__ import annotations

from src.ai.risk_drivers import build_risk_drivers
from src.ai.risk_intelligence import (
    build_action_recommendations,
    build_risk_trend_summary,
    build_stability_summary,
    classify_risk_type,
)
from src.ai.trigger_engine import build_trigger_alerts
from src.api.attendance_engine import build_attendance_summary
from src.api.feature_summaries import (
    build_erp_summary_from_event,
    build_lms_summary_from_events,
)


def build_current_student_intelligence(
    *,
    prediction_rows: list,
    latest_prediction,
    lms_events: list,
    erp_event,
    erp_history: list | None = None,
    finance_event=None,
    finance_history: list | None = None,
    previous_prediction=None,
) -> dict:
    lms_summary = build_lms_summary_from_events(lms_events)
    erp_summary = build_erp_summary_from_event(erp_event)
    attendance_summary = build_attendance_summary(getattr(erp_event, "context_fields", None))
    all_drivers = build_risk_drivers(
        prediction=latest_prediction,
        lms_summary=lms_summary,
        erp_summary=erp_summary,
        attendance_summary=attendance_summary,
        finance_modifier=float(latest_prediction.finance_modifier),
        limit=None,
    )
    displayed_drivers = all_drivers[:3]
    risk_trend = build_risk_trend_summary(prediction_rows)
    stability = build_stability_summary(
        prediction=latest_prediction,
        prediction_rows=prediction_rows,
    )
    risk_type = classify_risk_type(all_drivers)
    recommended_actions = build_action_recommendations(
        risk_type=risk_type,
        drivers=all_drivers,
        final_risk_probability=float(latest_prediction.final_risk_probability),
    )
    ordered_erp_history = list(erp_history or [])
    previous_erp = ordered_erp_history[1] if len(ordered_erp_history) >= 2 else None
    ordered_finance_history = list(finance_history or [])
    previous_finance = ordered_finance_history[1] if len(ordered_finance_history) >= 2 else None
    trigger_alerts = build_trigger_alerts(
        current_prediction=latest_prediction,
        previous_prediction=previous_prediction,
        current_erp=erp_event,
        previous_erp=previous_erp,
        current_finance=finance_event,
        previous_finance=previous_finance,
        attendance_summary=attendance_summary,
    )

    return {
        "lms_summary": lms_summary,
        "erp_summary": erp_summary,
        "attendance_summary": attendance_summary,
        "drivers": displayed_drivers,
        "risk_trend": risk_trend,
        "stability": stability,
        "risk_type": risk_type,
        "recommended_actions": recommended_actions,
        "trigger_alerts": trigger_alerts,
    }
