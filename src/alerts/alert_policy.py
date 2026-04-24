from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


ESCALATION_DELTA = 0.10
REMINDER_COOLDOWN = timedelta(days=7)


@dataclass(frozen=True)
class AlertDecision:
    should_send: bool
    alert_type: str | None
    reason: str


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def evaluate_alert_decision(
    current_prediction,
    previous_prediction=None,
    last_alert_event=None,
) -> AlertDecision:
    if float(current_prediction.final_risk_probability) < 0.50:
        return AlertDecision(
            should_send=False,
            alert_type=None,
            reason="Student is not currently high risk.",
        )

    if previous_prediction is None or float(previous_prediction.final_risk_probability) < 0.50:
        return AlertDecision(
            should_send=True,
            alert_type="initial_high",
            reason="Student newly entered high-risk state.",
        )

    if (
        float(current_prediction.final_risk_probability)
        - float(previous_prediction.final_risk_probability)
        >= ESCALATION_DELTA
    ):
        return AlertDecision(
            should_send=True,
            alert_type="high_escalation",
            reason="High-risk probability worsened significantly since the last score.",
        )

    if last_alert_event is None:
        return AlertDecision(
            should_send=True,
            alert_type="high_reminder",
            reason="Student remains high risk and no prior alert record exists.",
        )

    sent_at = _as_utc(getattr(last_alert_event, "sent_at", None))
    created_at = _as_utc(getattr(current_prediction, "created_at", None)) or datetime.now(UTC)
    if sent_at is not None and created_at - sent_at >= REMINDER_COOLDOWN:
        return AlertDecision(
            should_send=True,
            alert_type="high_reminder",
            reason="Student remains high risk after the cooldown window.",
        )

    return AlertDecision(
        should_send=False,
        alert_type=None,
        reason="High-risk state already alerted recently with no major worsening.",
    )
