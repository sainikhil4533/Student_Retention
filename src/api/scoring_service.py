from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.alerts.alert_policy import AlertDecision, evaluate_alert_decision
from src.alerts.email_service import get_alert_recipient, is_smtp_configured
from src.alerts.student_warning_policy import (
    evaluate_student_warning_decision,
    should_escalate_to_faculty,
)
from src.ai.llm_service import generate_ai_insights
from src.api.attendance_engine import build_attendance_summary
from src.api.feature_summaries import (
    build_erp_summary_from_event,
    build_lms_summary_from_events,
)
from src.api.feature_assembler import FeatureAssembler
from src.api.student_intelligence import build_current_student_intelligence
from src.db.repository import EventRepository


def score_student_from_db(
    student_id: int,
    db: Session,
    prediction_service,
) -> dict:
    repository = EventRepository(db)
    profile = repository.get_student_profile(student_id)
    previous_prediction = repository.get_latest_prediction_for_student(student_id)
    lms_events = repository.get_lms_events_for_student(student_id)
    erp_event = repository.get_latest_erp_event(student_id)
    finance_event = repository.get_latest_finance_event(student_id)
    erp_history = repository.get_erp_event_history_for_student(student_id)
    finance_history = repository.get_finance_event_history_for_student(student_id)

    if not profile:
        raise ValueError("No student profile found for student.")
    if not lms_events:
        raise ValueError("No LMS events found for student.")
    if not erp_event:
        raise ValueError("No ERP event found for student.")

    demographics = {
        "gender": profile.gender,
        "highest_education": profile.highest_education,
        "age_band": profile.age_band,
        "disability_status": profile.disability_status,
        "num_previous_attempts": float(profile.num_previous_attempts),
    }

    lms_summary = build_lms_summary_from_events(lms_events)
    erp_summary = build_erp_summary_from_event(erp_event)
    attendance_summary = build_attendance_summary(erp_event.context_fields)

    prediction_payload = FeatureAssembler.build_prediction_payload(
        demographics=demographics,
        lms_summary=lms_summary,
        erp_summary=erp_summary,
    )
    prediction_context = {
        **prediction_payload,
        "attendance_summary": attendance_summary,
    }

    prediction_result = prediction_service.predict_all_models(prediction_payload)
    champion_prediction = prediction_result["champion_prediction"]
    finance_result = prediction_service.apply_finance_modifier(
        champion_prediction["predicted_risk_probability"],
        {
            "modifier_candidate": finance_event.modifier_candidate if finance_event else 0.0,
        }
        if finance_event
        else None,
    )
    final_predicted_class = int(
        finance_result["final_probability"] >= prediction_service.threshold
    )
    risk_level = "HIGH" if final_predicted_class == 1 else "LOW"
    current_prediction = repository.add_prediction_history(
        {
            "student_id": student_id,
            "champion_model": champion_prediction["model_name"],
            "threshold": float(prediction_service.threshold),
            "base_predicted_class": int(champion_prediction["predicted_class"]),
            "base_risk_probability": float(
                champion_prediction["predicted_risk_probability"]
            ),
            "finance_modifier": float(finance_result["finance_modifier"]),
            "final_risk_probability": float(finance_result["final_probability"]),
            "final_predicted_class": int(final_predicted_class),
            "challenger_predictions": prediction_result["challenger_predictions"],
            "ai_insights": None,
        }
    )
    prediction_rows = repository.get_prediction_history_for_student(student_id)
    operational_intelligence = build_current_student_intelligence(
        prediction_rows=prediction_rows,
        latest_prediction=current_prediction,
        lms_events=lms_events,
        erp_event=erp_event,
        erp_history=erp_history,
        finance_event=finance_event,
        finance_history=finance_history,
        previous_prediction=previous_prediction,
    )
    ai_insights = generate_ai_insights(
        student_data=prediction_context,
        risk_score=float(champion_prediction["predicted_risk_probability"]),
        risk_level=risk_level,
        final_risk_probability=float(finance_result["final_probability"]),
        threshold=float(prediction_service.threshold),
        finance_modifier=float(finance_result["finance_modifier"]),
        operational_context={
            "risk_trend": operational_intelligence["risk_trend"],
            "stability": operational_intelligence["stability"],
            "risk_type": operational_intelligence["risk_type"],
            "recommended_actions": operational_intelligence["recommended_actions"],
            "trigger_alerts": operational_intelligence["trigger_alerts"],
        },
    )
    repository.update_prediction_history(
        current_prediction.id,
        {
            "ai_insights": ai_insights,
            "risk_trend": operational_intelligence["risk_trend"],
            "stability": operational_intelligence["stability"],
            "risk_type": operational_intelligence["risk_type"],
            "recommended_actions": operational_intelligence["recommended_actions"],
            "trigger_alerts": operational_intelligence["trigger_alerts"],
        },
    )
    print(
        f"[scoring] student_id={student_id} "
        f"risk_level={risk_level} ai_source={ai_insights.get('source')} "
        f"stability={operational_intelligence['stability'].get('stability_label')} "
        f"attendance_flag={attendance_summary.get('attendance_flag')}"
    )

    active_warning = repository.get_active_student_warning_for_student(student_id)
    warning_decision = evaluate_student_warning_decision(
        current_prediction=current_prediction,
        active_warning_event=active_warning,
    )
    student_warning_triggered = False
    student_warning_status: str | None = None
    student_warning_type: str | None = warning_decision.warning_type
    student_warning_event_id: int | None = None
    recovery_deadline = warning_decision.recovery_deadline

    if warning_decision.should_send and warning_decision.warning_type is not None:
        recipient = profile.student_email
        if recipient is None or not recipient.strip():
            student_warning_status = "skipped"
            warning_error = "Student email is not configured."
        elif not is_smtp_configured():
            student_warning_status = "skipped"
            warning_error = "SMTP configuration is incomplete."
        else:
            student_warning_status = "pending"
            warning_error = None

        warning_event = repository.add_student_warning_event(
            {
                "student_id": student_id,
                "prediction_history_id": current_prediction.id,
                "warning_type": warning_decision.warning_type,
                "risk_level": risk_level,
                "final_risk_probability": float(current_prediction.final_risk_probability),
                "recipient": recipient or "unconfigured",
                "delivery_status": student_warning_status,
                "error_message": warning_error,
                "recovery_deadline": recovery_deadline,
            }
        )
        student_warning_triggered = True
        student_warning_event_id = warning_event.id
        active_warning = warning_event
        print(
            f"[warnings] student_id={student_id} warning_type={warning_decision.warning_type} "
            f"status={student_warning_status}"
        )
    elif int(current_prediction.final_predicted_class) == 0 and active_warning is not None:
        repository.update_student_warning_event(
            active_warning.id,
            {
                "resolved_at": datetime.now(UTC),
                "resolution_status": "recovered",
            },
        )
        print(f"[warnings] student_id={student_id} resolved=recovered")

    last_alert_event = repository.get_latest_alert_for_student(student_id)
    should_faculty_alert, faculty_alert_reason = should_escalate_to_faculty(
        current_prediction=current_prediction,
        active_warning_event=active_warning,
    )
    alert_status: str | None = None
    alert_event_id: int | None = None

    if should_faculty_alert:
        if last_alert_event is None:
            alert_decision = AlertDecision(
                should_send=True,
                alert_type="post_warning_escalation",
                reason=faculty_alert_reason,
            )
        else:
            alert_decision = evaluate_alert_decision(
                current_prediction=current_prediction,
                previous_prediction=previous_prediction,
                last_alert_event=last_alert_event,
            )
    else:
        alert_decision = None

    if alert_decision and alert_decision.should_send and alert_decision.alert_type is not None:
        recipient = get_alert_recipient(profile)
        if recipient is None:
            alert_status = "skipped"
            error_message = "Faculty alert recipient is not configured."
        elif not is_smtp_configured():
            alert_status = "skipped"
            error_message = "SMTP configuration is incomplete."
        else:
            alert_status = "pending"
            error_message = None

        alert_event = repository.add_alert_event(
            {
                "student_id": student_id,
                "prediction_history_id": current_prediction.id,
                "alert_type": alert_decision.alert_type,
                "risk_level": risk_level,
                "final_risk_probability": float(current_prediction.final_risk_probability),
                "recipient": recipient or "unconfigured",
                "email_status": alert_status,
                "error_message": error_message,
            }
        )
        alert_event_id = alert_event.id
        if active_warning is not None:
            repository.update_student_warning_event(
                active_warning.id,
                {
                    "resolved_at": datetime.now(UTC),
                    "resolution_status": "escalated_to_faculty",
                },
            )
        print(
            f"[alerts] student_id={student_id} alert_type={alert_decision.alert_type} "
            f"status={alert_status}"
        )
    else:
        print(f"[alerts] student_id={student_id} skipped reason={faculty_alert_reason}")

    return {
        "champion_prediction": champion_prediction,
        "challenger_predictions": prediction_result["challenger_predictions"],
        "finance_modifier": finance_result["finance_modifier"],
        "final_risk_probability": finance_result["final_probability"],
        "final_predicted_class": final_predicted_class,
        "ai_insights": ai_insights,
        "risk_trend": operational_intelligence["risk_trend"],
        "stability": operational_intelligence["stability"],
        "risk_type": operational_intelligence["risk_type"],
        "recommended_actions": operational_intelligence["recommended_actions"],
        "trigger_alerts": operational_intelligence["trigger_alerts"],
        "student_warning_triggered": student_warning_triggered,
        "student_warning_status": student_warning_status,
        "student_warning_type": student_warning_type,
        "recovery_deadline": recovery_deadline,
        "student_warning_event_id": student_warning_event_id,
        "alert_triggered": bool(alert_decision and alert_decision.should_send),
        "alert_type": alert_decision.alert_type if alert_decision else None,
        "alert_status": alert_status,
        "alert_event_id": alert_event_id,
        "prediction_history_id": current_prediction.id,
    }
