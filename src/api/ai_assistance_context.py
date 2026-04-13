from __future__ import annotations

from src.api.operational_context import (
    build_activity_summary,
    build_milestone_flags,
    build_sla_summary,
)
from src.api.student_intelligence import build_current_student_intelligence


def build_live_case_context(*, repository, student_id: int) -> dict:
    profile = repository.get_student_profile(student_id)
    latest_prediction = repository.get_latest_prediction_for_student(student_id)
    prediction_rows = repository.get_prediction_history_for_student(student_id)
    lms_events = repository.get_lms_events_for_student(student_id)
    latest_erp_event = repository.get_latest_erp_event(student_id)
    erp_history = repository.get_erp_event_history_for_student(student_id)
    latest_finance_event = repository.get_latest_finance_event(student_id)
    finance_history = repository.get_finance_event_history_for_student(student_id)
    warning_history = repository.get_student_warning_history_for_student(student_id)
    latest_warning = warning_history[0] if warning_history else None
    alert_history = repository.get_alert_history_for_student(student_id)
    latest_alert = alert_history[0] if alert_history else None
    intervention_history = repository.get_intervention_history_for_student(student_id)
    latest_intervention = intervention_history[0] if intervention_history else None
    guardian_alert_history = repository.get_guardian_alert_history_for_student(student_id)
    latest_guardian_alert = guardian_alert_history[0] if guardian_alert_history else None

    intelligence = None
    if latest_prediction is not None and lms_events and latest_erp_event is not None:
        intelligence = build_current_student_intelligence(
            prediction_rows=prediction_rows,
            latest_prediction=latest_prediction,
            lms_events=lms_events,
            erp_event=latest_erp_event,
            erp_history=erp_history,
            finance_event=latest_finance_event,
            finance_history=finance_history,
            previous_prediction=prediction_rows[1] if len(prediction_rows) >= 2 else None,
        )

    activity_summary = build_activity_summary(
        lms_events=lms_events,
        erp_event=latest_erp_event,
        finance_event=latest_finance_event,
    )
    milestone_flags = (
        build_milestone_flags(
            profile=profile,
            erp_event=latest_erp_event,
            finance_event=latest_finance_event,
        )
        if profile is not None
        else None
    )
    sla_summary = build_sla_summary(
        latest_prediction=latest_prediction,
        latest_warning=latest_warning,
        latest_alert=latest_alert,
        intervention_history=intervention_history,
    )

    return {
        "profile": profile,
        "latest_prediction": latest_prediction,
        "prediction_history": prediction_rows,
        "lms_events": lms_events,
        "latest_erp_event": latest_erp_event,
        "latest_finance_event": latest_finance_event,
        "latest_warning": latest_warning,
        "latest_alert": latest_alert,
        "latest_intervention": latest_intervention,
        "intervention_history": intervention_history,
        "latest_guardian_alert": latest_guardian_alert,
        "guardian_alert_history": guardian_alert_history,
        "intelligence": intelligence,
        "activity_summary": activity_summary,
        "milestone_flags": milestone_flags,
        "sla_summary": sla_summary,
    }
