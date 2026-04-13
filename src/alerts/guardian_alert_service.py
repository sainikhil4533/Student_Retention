from __future__ import annotations

from dataclasses import dataclass

from src.alerts.guardian_alert_policy import (
    GuardianEscalationDecision,
    evaluate_guardian_escalation_decision,
)
from src.db.repository import EventRepository
from src.worker.job_queue import enqueue_guardian_alert_delivery_job


@dataclass
class GuardianEscalationAssessment:
    student_id: int
    should_send: bool
    alert_type: str | None
    reason: str
    channel: str | None
    severity: str
    recipient: str | None
    guardian_name: str | None
    guardian_relationship: str | None
    guardian_contact_enabled: bool
    repeat_high_risk_count: int
    high_risk_cycle_count: int
    has_relapsed_after_recovery: bool
    has_relapsed_after_resolution: bool
    is_critical_unattended_case: bool
    latest_prediction_id: int | None


@dataclass
class GuardianEscalationQueueResult:
    queued: bool
    deduplicated: bool
    message: str
    assessment: GuardianEscalationAssessment
    alert_event: object | None = None


def _build_repeated_risk_summary(history, intervention_history) -> dict:
    ordered = list(reversed(history))
    high_risk_prediction_count = sum(1 for row in ordered if int(row.final_predicted_class) == 1)
    resolution_times = sorted(
        row.created_at
        for row in intervention_history
        if str(row.action_status).strip().lower() == "resolved" and row.created_at is not None
    )

    high_risk_cycle_count = 0
    previous_was_high = False
    has_relapsed_after_recovery = False
    has_relapsed_after_resolution = False
    has_seen_recovery = False

    for row in ordered:
        is_high = int(row.final_predicted_class) == 1
        if is_high and not previous_was_high:
            high_risk_cycle_count += 1
            if has_seen_recovery:
                has_relapsed_after_recovery = True
            if any(resolution_time < row.created_at for resolution_time in resolution_times):
                has_relapsed_after_resolution = True
        if not is_high:
            has_seen_recovery = True
        previous_was_high = is_high

    return {
        "repeat_high_risk_count": high_risk_prediction_count,
        "high_risk_cycle_count": high_risk_cycle_count,
        "has_relapsed_after_recovery": has_relapsed_after_recovery,
        "has_relapsed_after_resolution": has_relapsed_after_resolution,
    }


def _guardian_recipient(profile, channel: str | None) -> str | None:
    if channel == "email":
        return profile.parent_email
    if channel in {"sms", "whatsapp"}:
        return profile.parent_phone
    return None


def build_guardian_escalation_assessment(
    repository: EventRepository,
    student_id: int,
) -> GuardianEscalationAssessment:
    profile = repository.get_student_profile(student_id)
    if profile is None:
        return GuardianEscalationAssessment(
            student_id=student_id,
            should_send=False,
            alert_type=None,
            reason="Student profile not found, so guardian escalation cannot be evaluated.",
            channel=None,
            severity="blocked",
            recipient=None,
            guardian_name=None,
            guardian_relationship=None,
            guardian_contact_enabled=False,
            repeat_high_risk_count=0,
            high_risk_cycle_count=0,
            has_relapsed_after_recovery=False,
            has_relapsed_after_resolution=False,
            is_critical_unattended_case=False,
            latest_prediction_id=None,
        )

    latest_prediction = repository.get_latest_prediction_for_student(student_id)
    warning = repository.get_active_student_warning_for_student(student_id)
    if warning is None:
        warning_history = repository.get_student_warning_history_for_student(student_id)
        warning = warning_history[0] if warning_history else None
    latest_alert = repository.get_latest_alert_for_student(student_id)
    latest_intervention = repository.get_latest_intervention_for_student(student_id)
    prediction_history = repository.get_prediction_history_for_student(student_id)
    intervention_history = repository.get_intervention_history_for_student(student_id)

    repeated_risk = _build_repeated_risk_summary(prediction_history, intervention_history)
    intervention_status = (
        str(latest_intervention.action_status).strip().lower()
        if latest_intervention is not None and latest_intervention.action_status is not None
        else None
    )
    is_critical_unattended_case = bool(
        latest_alert is not None
        and latest_alert.alert_type == "faculty_followup_reminder"
        and intervention_status not in {"acknowledged", "seen", "contacted", "support_provided", "resolved"}
        and latest_prediction is not None
        and int(latest_prediction.final_predicted_class) == 1
    )

    if latest_prediction is None:
        decision = GuardianEscalationDecision(
            should_send=False,
            alert_type=None,
            reason="No prediction is available yet, so guardian escalation cannot be evaluated.",
            channel=None,
            severity="blocked",
        )
    else:
        decision = evaluate_guardian_escalation_decision(
            profile=profile,
            current_prediction=latest_prediction,
            latest_warning=warning,
            latest_alert=latest_alert,
            latest_intervention=latest_intervention,
            repeat_high_risk_count=int(repeated_risk["repeat_high_risk_count"]),
            high_risk_cycle_count=int(repeated_risk["high_risk_cycle_count"]),
            has_relapsed_after_resolution=bool(repeated_risk["has_relapsed_after_resolution"]),
            is_critical_unattended_case=is_critical_unattended_case,
        )

    return GuardianEscalationAssessment(
        student_id=student_id,
        should_send=bool(decision.should_send),
        alert_type=decision.alert_type,
        reason=decision.reason,
        channel=decision.channel,
        severity=decision.severity,
        recipient=_guardian_recipient(profile, decision.channel),
        guardian_name=profile.parent_name,
        guardian_relationship=profile.parent_relationship,
        guardian_contact_enabled=bool(profile.guardian_contact_enabled),
        repeat_high_risk_count=int(repeated_risk["repeat_high_risk_count"]),
        high_risk_cycle_count=int(repeated_risk["high_risk_cycle_count"]),
        has_relapsed_after_recovery=bool(repeated_risk["has_relapsed_after_recovery"]),
        has_relapsed_after_resolution=bool(repeated_risk["has_relapsed_after_resolution"]),
        is_critical_unattended_case=is_critical_unattended_case,
        latest_prediction_id=(int(latest_prediction.id) if latest_prediction is not None else None),
    )


def queue_guardian_escalation_if_eligible(
    repository: EventRepository,
    *,
    student_id: int,
    actor_role: str,
    actor_subject: str,
) -> GuardianEscalationQueueResult:
    assessment = build_guardian_escalation_assessment(repository, student_id)

    if not assessment.should_send or assessment.alert_type is None or assessment.channel is None:
        return GuardianEscalationQueueResult(
            queued=False,
            deduplicated=False,
            message="Guardian escalation is not eligible yet, so no guardian alert event was queued.",
            assessment=assessment,
            alert_event=None,
        )

    if assessment.latest_prediction_id is None or assessment.recipient in (None, ""):
        return GuardianEscalationQueueResult(
            queued=False,
            deduplicated=False,
            message="Guardian escalation is eligible in principle, but recipient or prediction context is incomplete.",
            assessment=assessment,
            alert_event=None,
        )

    existing = repository.find_existing_guardian_alert_for_prediction(
        student_id=student_id,
        prediction_history_id=assessment.latest_prediction_id,
        alert_type=assessment.alert_type,
    )
    if existing is not None:
        return GuardianEscalationQueueResult(
            queued=False,
            deduplicated=True,
            message="A guardian escalation event already exists for the current prediction cycle.",
            assessment=assessment,
            alert_event=existing,
        )

    latest_prediction = repository.get_prediction_history_by_id(assessment.latest_prediction_id)
    if latest_prediction is None:
        return GuardianEscalationQueueResult(
            queued=False,
            deduplicated=False,
            message="Prediction context not found for guardian escalation.",
            assessment=assessment,
            alert_event=None,
        )

    context_snapshot = {
        "reason": assessment.reason,
        "severity": assessment.severity,
        "channel": assessment.channel,
        "repeat_high_risk_count": assessment.repeat_high_risk_count,
        "high_risk_cycle_count": assessment.high_risk_cycle_count,
        "has_relapsed_after_recovery": assessment.has_relapsed_after_recovery,
        "has_relapsed_after_resolution": assessment.has_relapsed_after_resolution,
        "is_critical_unattended_case": assessment.is_critical_unattended_case,
        "queued_by_role": actor_role,
        "queued_by_subject": actor_subject,
    }

    alert_event = repository.add_guardian_alert_event(
        {
            "student_id": student_id,
            "prediction_history_id": assessment.latest_prediction_id,
            "alert_type": assessment.alert_type,
            "risk_level": "HIGH" if int(latest_prediction.final_predicted_class) == 1 else "LOW",
            "final_risk_probability": float(latest_prediction.final_risk_probability),
            "guardian_name": assessment.guardian_name,
            "guardian_relationship": assessment.guardian_relationship,
            "recipient": assessment.recipient,
            "channel": assessment.channel,
            "delivery_status": "queued",
            "provider_name": None,
            "provider_message_id": None,
            "retry_count": 0,
            "error_message": None,
            "context_snapshot": context_snapshot,
        }
    )
    enqueue_guardian_alert_delivery_job(guardian_alert_event_id=int(alert_event.id))

    return GuardianEscalationQueueResult(
        queued=True,
        deduplicated=False,
        message="Guardian escalation event has been queued for background delivery handling.",
        assessment=assessment,
        alert_event=alert_event,
    )
